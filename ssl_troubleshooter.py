#!/usr/bin/env python3
import argparse
import subprocess
import sys
import json
import os
import re
import textwrap

PROXY = "socks5h://127.0.0.1:1080"

VALID_CLUSTERS = {
    "c11": "c11.hamravesh.onhamravesh.ir",
    "c13": "c13.hamravesh.onhamravesh.ir",
    "c23": "c23.hamravesh.onhamravesh.ir"
}

IP_REGEX = re.compile(r"^\d+\.\d+\.\d+\.\d+$")


# =========================================================
# UTIL
# =========================================================

def section(t):
    print("\n" + "="*60)
    print(t)
    print("="*60)


def run(cmd, proxy=False, capture=True, input_text=None):

    env = None
    if proxy:
        env = os.environ.copy()
        env["HTTP_PROXY"] = PROXY
        env["HTTPS_PROXY"] = PROXY
        env["ALL_PROXY"] = PROXY

    result = subprocess.run(
        cmd,
        shell=True,
        text=True,
        input=input_text,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        env=env
    )

    if result.returncode != 0:
        print("\n❌ Command failed:\n", cmd)
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr)
        sys.exit(1)

    return result.stdout.strip() if capture else ""


def kubectl_json(resource):
    return json.loads(run(f"kubectl get {resource} -o json", proxy=True))


# =========================================================
# CONTEXT
# =========================================================

def switch_context(cluster, namespace):
    section("Switching Context")

    run(f"kubectx hamravesh-{cluster}", proxy=True, capture=False)
    run(f"kubens {namespace}", proxy=True, capture=False)

    print("✔ Context ready")


# =========================================================
# TEMP ACCESS
# =========================================================

def apply_temp_access(namespace, user):
    section("Applying TempAccess")

    manifest = textwrap.dedent(f"""
    apiVersion: security.hamravesh.com/v1alpha1
    kind: TempAccess
    metadata:
      name: ssl-check
    spec:
      username: hamravesh:{user}
      ttl: 1h
      rules:
        - namespace: "{namespace}"
          apiGroups: ["*"]
          resources: ["*"]
          verbs: ["*"]
    """)

    run("kubectl apply -f -", proxy=True, capture=False, input_text=manifest)
    print("✔ Temp access granted")


# =========================================================
# DNS
# =========================================================

def only_ips(lines):
    return {l.strip(".") for l in lines.splitlines() if IP_REGEX.match(l.strip("."))}


def check_dns(domain, expected_host):
    print(f"\n→ Checking DNS for {domain}")

    res = run(f"dig +short {domain}")
    if not res:
        print("   ❌ No DNS record")
        return False

    expected = run(f"dig +short {expected_host}")

    d_ips = only_ips(res)
    e_ips = only_ips(expected)

    if d_ips & e_ips:
        print("   ✔ DNS OK")
        return True

    print("   ❌ DNS mismatch")
    return False


# =========================================================
# NAME HELPERS
# =========================================================

def workload_from_pod(pod):
    parts = pod.split("-")
    if len(parts) <= 2:
        return pod
    return "-".join(parts[:-2])


# =========================================================
# INGRESS DISCOVERY
# =========================================================

def find_domains(pod, app_type):
    section("Finding Domains From Ingress")

    ing = kubectl_json("ingress")["items"]

    domains = []

    if app_type == "marketplace":

        for item in ing:
            name = item["metadata"]["name"]

            if pod in name:
                rules = item.get("spec", {}).get("rules", [])
                for r in rules:
                    if "host" in r:
                        domains.append(r["host"])

    else:  # darkube

        base = workload_from_pod(pod)

        for item in ing:
            name = item["metadata"]["name"]

            if name == base:
                rules = item.get("spec", {}).get("rules", [])
                for r in rules:
                    if "host" in r:
                        domains.append(r["host"])

    domains = sorted(set(domains))

    if not domains:
        print("❌ No ingress domains found")
        sys.exit(1)

    for d in domains:
        print("✔", d)

    return domains


# =========================================================
# CERT CHECK
# =========================================================

def cert_ready(cert):
    conds = cert.get("status", {}).get("conditions", [])
    return any(c["type"] == "Ready" and c["status"] == "True" for c in conds)


def check_cert_manager(pod, app_type):
    section("Cert Manager")

    base = pod if app_type == "marketplace" else workload_from_pod(pod)
    cert_name = f"{base}-tls"
    prefix = f"{base}-tls"

    certs = kubectl_json("certificates")["items"]
    cert = next((c for c in certs if c["metadata"]["name"] == cert_name), None)

    if cert and cert_ready(cert):
        print(f"✔ Certificate {cert_name} READY")
        print("\n✅ SSL is valid")
        return True

    print("❌ Certificate not ready")

    # -------- Requests
    reqs = [
        r for r in kubectl_json("certificaterequests")["items"]
        if r["metadata"]["name"].startswith(prefix)
    ]

    if reqs:
        print("\nCertificateRequests:")
        for r in reqs:
            print(" •", r["metadata"]["name"])

    # -------- Orders
    orders = [
        o for o in kubectl_json("orders.acme.cert-manager.io")["items"]
        if o["metadata"]["name"].startswith(prefix)
    ]

    if orders:
        print("\nOrders:")
        for o in orders:
            name = o["metadata"]["name"]
            state = o.get("status", {}).get("state")
            print(" •", name, "|", state)

    # -------- Challenges
    chals = [
        c for c in kubectl_json("challenges.acme.cert-manager.io")["items"]
        if c["metadata"]["name"].startswith(prefix)
    ]

    if chals:
        print("\nChallenges:")
        for c in chals:
            name = c["metadata"]["name"]
            state = c.get("status", {}).get("state")
            dom = c.get("spec", {}).get("dnsName")
            print(" •", name, "|", dom, "|", state)

    return False


# =========================================================
# MAIN
# =========================================================

def main():

    parser = argparse.ArgumentParser()

    parser.add_argument("--cluster", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--pod", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--app-type", required=True, choices=["marketplace","darkube"])

    args = parser.parse_args()

    if args.cluster not in VALID_CLUSTERS:
        print("Invalid cluster")
        sys.exit(1)

    expected_host = VALID_CLUSTERS[args.cluster]

    switch_context(args.cluster, args.namespace)
    apply_temp_access(args.namespace, args.user)

    domains = find_domains(args.pod, args.app_type)

    section("DNS Checks")
    for d in domains:
        check_dns(d, expected_host)

    ok = check_cert_manager(args.pod, args.app_type)

    section("Result")

    if ok:
        print("✔ SSL healthy")
    else:
        print("❌ SSL has issues")


if __name__ == "__main__":
    main()
