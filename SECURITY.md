# Security Policy

## Reporting a vulnerability

Please **do not open a public issue** for a security vulnerability.

Report it privately through
[GitHub Security Advisories](https://github.com/AFZ92/huawei-ar730-router-easy-manager/security/advisories/new),
or by email to **amjadzarour@gmail.com**.

Please include a description, reproduction steps, and the impact you believe it has. You can
expect an acknowledgement within a few days.

## Scope

This is a desktop tool that authenticates to network hardware over SSH. Reports about the
following are in scope:

- Leakage of credentials (the SSH password, or the shared MAC-authentication password)
- Command injection into the VRP session through interface fields
- Weakening of SSH host verification or transport security
- Local data written with unsafe permissions

## Design decisions that are intentional

- **The SSH password is never persisted.** It is requested at every launch. This is by design
  and will not change.
- **`ar730_devices.json` is stored unencrypted.** It contains device owner names, not
  credentials. Treat it as personal data under your local obligations.
- **`ar730_session.log` contains full session transcripts**, including configuration dumps
  with cipher-text password hashes. It is gitignored. Redact it before sharing.

## Hardening the deployment

- Restrict router management to your management networks with an ACL, and run this tool only
  from inside them.
- Do not expose SSH to the internet to widen access. Use a VPN into the management network.
- Give the tool an SSH account with the least privilege that still permits the `aaa`
  operations it performs.
