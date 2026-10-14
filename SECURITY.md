# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.2.x   | :white_check_mark: |
| < 1.2.0 | :x:                |

## Reporting a Vulnerability

We take the security of LeanStack seriously. If you discover a security vulnerability or weakness within the control plane, Angie/WAF rulesets, or isolation boundary, please follow responsible disclosure guidelines:

1. **Do NOT open a public GitHub Issue.**
2. Report the vulnerability privately via **GitHub Security Advisories** on the repository ("Report a vulnerability" under the Security tab).
3. Alternatively, email the maintainer directly at **security@kuntalghosh.dev** with detailed steps to reproduce the issue.

### What to Include:
* Description of the vulnerability and attack vector.
* Affected components (`lsctl`, `vhost.conf.tpl`, `pool.conf.tpl`, etc.).
* Step-by-step reproduction guide or proof-of-concept.
* Impact assessment on isolation or privilege escalation.

### Response Timeline:
* **Initial response:** Within 48 hours.
* **Triage & severity rating:** Within 5 business days.
* **Fix & advisory publication:** Coordinated after a patched release is tagged.
