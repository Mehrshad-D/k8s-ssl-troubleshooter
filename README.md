# SSL Troubleshooter

Automated diagnostic tool for debugging SSL certificate issues in Hamravesh Kubernetes clusters.

This script helps platform engineers quickly identify why an SSL certificate is not issued or valid by checking:

* DNS configuration
* Ingress configuration
* Certificate resources
* CertificateRequests
* Orders
* Challenges

It supports both **Marketplace apps** and **Darkube apps**, which use different naming conventions.

---

# Features

* Automatic context + namespace switching
* Temporary access creation
* Domain discovery from ingress
* DNS validation
* Certificate readiness detection
* Detailed status output for all related cert-manager resources
* SOCKS5 proxy support for kubectl only
* Multi-domain support
* Early exit when SSL is valid

---

# Supported App Types

## Marketplace Apps

Naming pattern:

Pod:

```
oneclick-appname-xxxxx
```

Resources:

```
Certificate:           oneclick-appname-xxxxx-tls
CertificateRequest:    oneclick-appname-xxxxx-tls-1
Order:                 oneclick-appname-xxxxx-tls-1-123456
```

Ingress detection rule:

```
Ingress name contains pod name
```

---

## Darkube Apps

Naming pattern:

Pod:

```
appname-<hash>-<id>
```

Resources:

```
Certificate:           appname-tls
CertificateRequest:    appname-tls-xxxxx
Order:                 appname-tls-xxxxx-123456
```

Ingress detection rule:

```
Ingress name == workload name
```

Workload name is extracted automatically from pod name.

---

# Requirements

* Python 3.9+
* kubectl
* kubectx
* kubens
* dig
* hamctl proxy access

---

# Proxy Requirement

This script assumes the Hamravesh SOCKS5 proxy is running:

```
hamctl proxy --host 127.0.0.1 --port 1080 --request-missing
```

Only kubectl commands use the proxy. DNS queries do not.

---

# Installation

Clone repository:

```
git clone https://github.com/YOUR_REPO/ssl-troubleshooter.git
cd ssl-troubleshooter
chmod +x ssl_troubleshooter.py
```

---

# Usage

```
python3 ssl_troubleshooter.py \
  --cluster c13 \
  --namespace mynamespace \
  --pod mypod-abc123 \
  --user your.username \
  --app-type marketplace
```

---

# Arguments

| Argument    | Description                    |
| ----------- | ------------------------------ |
| --cluster   | Target cluster (c11, c13, c23) |
| --namespace | Kubernetes namespace           |
| --pod       | Pod name                       |
| --user      | Hamravesh username             |
| --app-type  | marketplace or darkube         |

---

# Output Stages

Script prints results step-by-step:

1. Context switch
2. TempAccess apply
3. Ingress domain discovery
4. DNS verification
5. Certificate validation
6. Detailed resource states (if failed)

---

# Success Example

```
✔ site.example.com DNS OK
✔ Certificate test-app-tls READY

Result
✔ SSL healthy
```

---

# Failure Example

```
❌ Certificate not ready

Orders:
 • test-app-tls-abcde | pending

Challenges:
 • test-app-tls-abcde-123456 | site.example.com | pending

Result
❌ SSL has issues
```

---

# How It Works Internally

Flow:

```
Switch Context
     ↓
Apply TempAccess
     ↓
Find Domains From Ingress
     ↓
Check DNS
     ↓
Check Certificate
     ↓
If invalid → Inspect Requests / Orders / Challenges
```

---

# Exit Logic

If certificate is valid → script stops early and reports success.

This prevents unnecessary API calls and speeds up checks.

---

# Safety

* Read-only except TempAccess
* Namespace-scoped
* 1-hour temporary permissions
* No destructive operations

---

# Troubleshooting

## Proxy errors

Make sure proxy is running:

```
lsof -i :1080
```

---

## kubectl permission denied

Re-run script — TempAccess may not be applied yet.

---

## No domains found

Check:

* ingress exists
* correct app type specified

---

# Author

Mehrshad Dehghani
