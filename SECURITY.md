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

## Known limitations

### Decrypted temporary copies after an abrupt exit while compressing

To compress an encrypted PDF, the Compress tool works on decrypted temporary copies. All of them, Ghostscript's own scratch files included, are made in one folder per operation, `pdfapps-compress-*`, inside the system's temporary folder (`%TEMP%` on Windows, usually `/tmp` on Linux). The folder is deleted when the operation ends, whether it succeeds, fails or is cancelled, provided that nothing is still using it. On a cancel, and when Ghostscript runs past its time limit, Ghostscript is told to stop and given a few seconds to exit; a Ghostscript still running after that can keep the folder from being deleted (measured with a stand-in that outlived the request). The folder then stays, with what Ghostscript writes in it, and the only sign of it is a warning naming the folder in the application's log, `pdfapps.log`, next to the settings file. If the application dies abruptly in the middle of it (killed process, power loss), the folder and the copies in it stay there, and the next start does not remove them. If Ghostscript is running at that moment, it is not stopped with the application: it carries on and finishes its copy in the same folder.

Who else can open that folder:

| System | Who else |
|--------|----------|
| Windows | SYSTEM and Administrators: the folder has its own restricted access list, which the files in it inherit |
| Linux | root: the folder has mode 0700, whatever the mode of the files in it |
| Linux, Snap | Not measured. The Snap runs under strict confinement, where snapd gives the application a private `/tmp` of its own; where that is on the host, and who can open it there, was not measured |
| macOS | Not measured. The folder is made in the same way as on Linux |

Measured on Windows 11 and Ubuntu 26.04 with Python 3.14, the version the Windows build uses. On Windows the restricted access list comes from Python itself (its fix for CVE-2024-4030); run from source with a Python that lacks that fix, the folder inherits the access list of the temporary folder instead.

This limit is accepted for version 1.15.3. A later version is meant to remove these folders at startup. Until then, after such an exit, delete the `pdfapps-compress-*` folders in the temporary folder by hand.
