# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-08-23

First public release.

### Added

- Trusted-device management: add, revoke, and change permission groups for MAC-authenticated
  devices, with the command ordering the hardware requires.
- Captive-portal account management: create, delete, reset passwords, change groups.
- Live session view with the ability to cut a session or promote a connected device into the
  whitelist.
- Permission-group listing with the ACL number bound to each group.
- Live search across every table, filtering by MAC, name, status, group, IP and note. MAC
  matching ignores separators.
- Editable local records — owner name and note — stored outside the router and editable with
  no connection.
- Revocation that preserves an audit trail: removed from the router, retained locally as
  revoked with date and reason.
- Full command log of every request and reply.
- Bilingual interface, English and Arabic, with right-to-left layout mirroring.
- Offline router simulator (`--demo`) enforcing the real device's constraints.
- Configurable SSH port; empty means 22.
- Headless test harness with 210 checks across two suites, requiring no display or hardware.

### Security

- The SSH password is never written to disk.
- Runtime data files are excluded from version control.

[1.0.0]: https://github.com/AFZ92/ar730-access-manager/releases/tag/v1.0.0
