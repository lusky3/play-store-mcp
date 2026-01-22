# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

We take security vulnerabilities seriously. If you discover a security issue, please use GitHub's built-in security advisory feature to report it privately.

### How to Report

1. Go to the [Security Advisories](https://github.com/lusky3/play-store-mcp/security/advisories) page
2. Click **"New draft security advisory"**
3. Fill in the details about the vulnerability
4. Submit the advisory

We will respond within 48 hours and work with you to understand and address the issue.

### What to Include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if you have one)

### What to Expect

- Acknowledgment within 48 hours
- Regular updates on our progress
- Credit in the security advisory (unless you prefer to remain anonymous)

## Security Best Practices for Users

- **Never commit service account keys** to version control
- Use environment variables for `GOOGLE_APPLICATION_CREDENTIALS`
- Limit service account permissions to only what's needed
- Rotate service account keys regularly
