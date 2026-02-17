#!/usr/bin/env python3
import argparse
import subprocess
import sys
import textwrap
import json
import os
import re

PROXY = "socks5h://127.0.0.1:1080"
ARVAN_IPS = {"185.143.234.235", "185.143.233.235"}

VALID_CLUSTERS = {
    "c11": "c11.hamravesh.onhamravesh.ir",
    "c13": "c13.hamravesh.onhamravesh.ir",
    "c23": "c23.hamravesh.onhamravesh.ir"
}


# ---------------- UTIL ---------------- #

def run(cmd, capture=True, proxy=False):
    env = None
    if proxy:
        env = os.environ.copy()
        env["ALL_PROXY"] = PROXY
        env["HTTPS_PROXY"] = PROXY
        env["HTTP_PROXY"] = PROXY

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            check=True,
            text=True,
            env=env,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None
        )
        return result.stdout.strip() if capture else ""
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Command failed:\n{cmd}\n")
        if e.stdout:
            print(e.stdout)
        if e.stderr:
            print(e.stderr)
        sys.exit(1)


def section(title):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


# ---------------- STEPS ---------------- #

def switch_context(cluster, namespace):
    section("Switching Context")

    print("→ Switching cluster...")
    run(f"kubectx hamravesh-{cluster}", capture=False, proxy=True)

    print("→ Switching namespace...")
    run(f"kubens {namespace}", capture=False, proxy=True)

    print("✔ Context ready")


def apply_temp_access(namespace, user):
    section("Applying TempAccess")

    manifest = textwrap.dedent(f"""
    apiVersion: security.hamravesh.com/v1alpha1
    kind: TempAccess
    metadata:
      name: check-podssssss
    spec:
      username: hamravesh:{user}
      ttl: 1h
      rules:
        - namespace: "{namespace}"
          apiGroups: ["*"]
          resources: ["*"]
          verbs: ["*"]
    """)

    env = os.environ.copy()
    env["ALL_PROXY"] = PROXY
    env["HTTPS_PROXY"] = PROXY
    env["HTTP_PROXY"] = PROXY

    result = subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=manifest,
        text=True,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    if result.returncode != 0:
        print("❌ Failed applying TempAccess\n")
        print(result.stderr)
        sys.exit(1)

    print(result.stdout.strip())
    print("✔ Temp access granted")



IP_REGEX = re.compile(r"^\d+\.\d+\.\d+\.\d+$")

def only_ips(lines):
    return {l.strip(".") for l in lines.splitlines() if IP_REGEX.match(l.strip("."))}


def check_dns(domain, expected_host):
    section("DNS Check")

    print(f"→ Resolving {domain}")
    output = run(f"dig +short {domain}")

    if not output:
        print("❌ Domain does not resolve")
        return False

    print(f"Resolved records:\n{output}")

    print("\n→ Resolving expected cluster host")
    expected = run(f"dig +short {expected_host}")
    print(f"{expected_host} →\n{expected}")

    domain_ips = only_ips(output)
    expected_ips = only_ips(expected)

    if not domain_ips:
        print("\n❌ No A records found for domain")
        return False

    # include Arvan IPs
    domain_ips = domain_ips | (domain_ips & ARVAN_IPS)

    if domain_ips == expected_ips or expected_ips & domain_ips or domain_ips & ARVAN_IPS:
        print("\n✔ DNS points to correct cluster or Arvan CDN")
        return True

    print("\n❌ DNS DOES NOT point to cluster ingress")
    return False


def kubectl_json(resource):
    out = run(f"kubectl get {resource} -o json", proxy=True)
    return json.loads(out)


# normalize pod → workload base name
def workload_name(pod):
    parts = pod.split("-")
    if len(parts) > 2:
        return "-".join(parts[:-2])
    return pod


def check_cert_manager(pod):
    section("Cert Manager Resources")

    cert_name = f"{pod}-tls"
    cert_request_prefix = f"{pod}-tls"
    order_prefix = f"{pod}-tls"

    # ---------------- Certificates ---------------- #
    try:
        certs = kubectl_json("certificates")
    except:
        print("No certificates found")
        certs = {"items": []}

    pod_cert = None
    for c in certs.get("items", []):
        if c["metadata"]["name"] == cert_name:
            pod_cert = c
            break

    if pod_cert:
        status = pod_cert.get("status", {})
        conditions = status.get("conditions", [])
        ready = any(c.get("type") == "Ready" and c.get("status") == "True" for c in conditions)
        if ready:
            print(f"✔ Certificate '{cert_name}' is Ready/Valid ✅")
            return  # Everything is OK, stop here
        else:
            print(f"❌ Certificate '{cert_name}' is NOT ready")
    else:
        print(f"❌ Certificate '{cert_name}' not found")

    # ---------------- CertificateRequests ---------------- #
    try:
        cert_reqs = kubectl_json("certificaterequests")
    except:
        cert_reqs = {"items": []}

    matched_reqs = [
        cr for cr in cert_reqs.get("items", [])
        if cr["metadata"]["name"].startswith(cert_request_prefix)
    ]

    if matched_reqs:
        print("\n--- CertificateRequests ---")
        for cr in matched_reqs:
            name = cr["metadata"]["name"]
            print(f"\n{name}")
            # Print some key info
            status = cr.get("status", {})
            conds = status.get("conditions", [])
            if conds:
                for c in conds:
                    print(f"  • {c.get('type')} = {c.get('status')} ({c.get('reason','')})")
            else:
                print("  No status conditions")
            # Describe full object
            describe = run(f"kubectl describe certificaterequest {name}", proxy=True)
            print(describe)
    else:
        print("\nNo CertificateRequests found for this pod")

    # ---------------- Orders ---------------- #
    try:
        orders = kubectl_json("orders.acme.cert-manager.io")
    except:
        orders = {"items": []}

    matched_orders = [
        o for o in orders.get("items", [])
        if o["metadata"]["name"].startswith(order_prefix)
    ]

    if matched_orders:
        print("\n--- Orders ---")
        for o in matched_orders:
            name = o["metadata"]["name"]
            state = o.get("status", {}).get("state", "Unknown")
            print(f"\n{name} | State: {state}")
            describe = run(f"kubectl describe order {name}", proxy=True)
            print(describe)
    else:
        print("\nNo Orders found for this pod")

    # ---------------- Challenges ---------------- #
    try:
        challenges = kubectl_json("challenges.acme.cert-manager.io")
    except:
        challenges = {"items": []}

    matched_chals = [
        ch for ch in challenges.get("items", [])
        if ch["metadata"]["name"].startswith(order_prefix)
    ]

    if matched_chals:
        print("\n--- Challenges ---")
        for ch in matched_chals:
            name = ch["metadata"]["name"]
            state = ch.get("status", {}).get("state", "Unknown")
            print(f"\n{name} | State: {state}")
            describe = run(f"kubectl describe challenge {name}", proxy=True)
            print(describe)
    else:
        print("\nNo Challenges found for this pod")



def ingress_check(domain):
    section("Ingress Check")

    try:
        ing = kubectl_json("ingress")
    except:
        print("No ingresses found")
        return

    found = False

    for item in ing["items"]:
        name = item["metadata"]["name"]
        rules = item.get("spec", {}).get("rules", [])

        for r in rules:
            if r.get("host") == domain:
                found = True
                print(f"✔ Domain found in ingress: {name}")

    if not found:
        print("❌ Domain not referenced in any ingress")


# ---------------- MAIN ---------------- #

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cluster", required=True, help="c11 | c13 | c23")
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--pod", required=True)
    parser.add_argument("--user", required=True)


    args = parser.parse_args()

    if args.cluster not in VALID_CLUSTERS:
        print("Invalid cluster. Must be: c11, c13, c23")
        sys.exit(1)

    expected_host = VALID_CLUSTERS[args.cluster]

    switch_context(args.cluster, args.namespace)
    apply_temp_access(args.namespace, args.user)
    check_dns(args.domain, expected_host)
    ingress_check(args.domain)
    check_cert_manager(args.pod)

    section("Done")


if __name__ == "__main__":
    main()
