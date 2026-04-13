# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| Latest  | Yes       |
| Older   | No        |

Only the latest release receives security updates. Please upgrade before reporting.

## Reporting a vulnerability

**Do not open a public issue for security vulnerabilities.**

Instead, use one of these methods:

1. **GitHub Private Vulnerability Reporting** (preferred)
   Go to [Security > Advisories > New draft advisory](https://github.com/nelsonduarte/PDFApps/security/advisories/new) and submit your report privately.

2. **Email**
   Contact the maintainer directly via the email address listed on the [GitHub profile](https://github.com/nelsonduarte).

### What to include

- Description of the vulnerability
- Steps to reproduce
- Affected version(s)
- Potential impact

### Response time

- **Acknowledgement**: within 48 hours
- **Fix or mitigation**: within 7 days for critical issues, 30 days for others

## Scope

PDFApps is a desktop application that runs entirely offline. The main attack surface is maliciously crafted PDF files. Network-related vulnerabilities only apply to the auto-updater module.
