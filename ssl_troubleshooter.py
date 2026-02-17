#!/usr/bin/env python3
import argparse
import subprocess
import sys
import textwrap
import json
import os
import re

PROXY = "socks5h://127.0.0.1:1080"

VALID_CLUSTERS = {
    "c11": "c11.hamravesh.onhamravesh.ir",
    "c13": "c13.hamravesh.onhamravesh.ir",
    "c23": "c23.hamravesh.onhamravesh.ir"
}


# ---------------- UTIL ---------------- #

def run(cmd, capture=True, proxy=False):
    env = None
    if proxy:
        import os
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


def apply_temp_access(namespace):
    section("Applying TempAccess")

    manifest = textwrap.dedent(f"""
    apiVersion: security.hamravesh.com/v1alpha1
    kind: TempAccess
    metadata:
      name: check-podssssss
    spec:
      username: hamravesh:mehrshad.dehghani
      ttl: 1h
      rules:
        - namespace: "{namespace}"
          apiGroups: ["*"]
          resources: ["*"]
          verbs: ["*"]
    """)

    env = os.environ.copy()
    env["ALL_PROXY"] = "socks5h://127.0.0.1:1080"
    env["HTTPS_PROXY"] = "socks5h://127.0.0.1:1080"
    env["HTTP_PROXY"] = "socks5h://127.0.0.1:1080"

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
        exit(1)

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

    if domain_ips == expected_ips:
        print("\n✔ DNS points to correct cluster")
        return True

    if domain_ips & expected_ips:
        print("\n⚠ DNS partially matches cluster IPs")
        return True

    print("\n❌ DNS DOES NOT point to cluster ingress")
    return False


def kubectl_json(resource):
    out = run(f"kubectl get {resource} -o json", proxy=True)
    return json.loads(out)


def check_cert_manager(pod):
    section("Cert Manager Resources")

    resources = [
        ("Certificates", "certificates"),
        ("CertificateRequests", "certificaterequests"),
        ("Orders", "orders.acme.cert-manager.io"),
        ("Challenges", "challenges.acme.cert-manager.io")
    ]

    for title, res in resources:
        print(f"\n--- {title} ---")

        try:
            data = kubectl_json(res)
        except:
            print("None found")
            continue

        matched = [
            item for item in data.get("items", [])
            if pod in item["metadata"]["name"]
        ]

        if not matched:
            print("None found")
            continue

        for item in matched:
            name = item["metadata"]["name"]
            status = item.get("status", {})
            conds = status.get("conditions", [])

            print(f"\n{name}")

            if conds:
                for c in conds:
                    print(
                        f"  • {c.get('type')} = {c.get('status')} "
                        f"({c.get('reason','')})"
                    )
            else:
                print("  No status conditions")



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

    args = parser.parse_args()

    if args.cluster not in VALID_CLUSTERS:
        print("Invalid cluster. Must be: c11, c13, c23")
        sys.exit(1)

    expected_host = VALID_CLUSTERS[args.cluster]

    switch_context(args.cluster, args.namespace)
    apply_temp_access(args.namespace)
    check_dns(args.domain, expected_host)
    ingress_check(args.domain)
    check_cert_manager(args.pod)

    section("Done")


if __name__ == "__main__":
    main()
