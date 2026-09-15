# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Optional Firebase Firestore synchronization: the application always writes its local JSON
  copy first, uploads changes automatically when online, retries each minute while a change is
  pending, and downloads newer shared records on other manager devices. Firebase connection
  details are entered from Settings; leaving them empty retains local-only operation.

- **Change & Apply Password** (Settings tab): changes the shared MAC password in
  `mac-access-profile` and in every MAC account in one operation, unblocks blocked accounts,
  re-reads the profile to confirm the change, and stops before touching any account if the
  router rejects the new password.
- **Internet Lines** tab: discovers every WAN line from its tracked default route and reports,
  per line, the router's rotation state, the ICMP probe (which makes the router drop a dead
  line), the HTTPS (TCP 443) probe that reveals an exhausted ISP quota, a live `ping -nexthop`
  latency and loss measurement, and the physical port speed, CRC errors and recent link drops.
  It also flags misconfigurations: probes that leave through another line, routes tied to non-ICMP
  probes (ignored by this firmware), and lines without an HTTPS probe.
- Take a line out of rotation and put it back exactly as it was; optional automatic monitoring that
  takes a quota-blocked line out after two failed checks and restores it after two good ones,
  never removing the last working line.
- **Management Devices** tab: lets a specific device reach router management over SSH from
  a user network without joining the management network. You choose the network, the address
  (or take the highest free one) and the basic ACL; the program validates every choice against
  the router (leases, existing bindings, static ARP, rule numbers, vty ACL binding, NAC trust,
  device port) and reports each problem. It then pins the address with a DHCP static binding,
  blocks spoofing with a static ARP entry, and adds a host permit rule before the deny rule
  (SSH access; the web page is left on the management port). A rejected step rolls back
  the earlier ones; success is confirmed by re-reading the router. Removal deletes the rule
  first and refuses to delete the address you are connected from.
- Blocked MAC accounts (`display local-user` state `B`) are shown in the Trusted Devices table
  and flagged in the status bar after every refresh and after adding a device.

### Documentation

- `docs/router/`: a reference of the AR730 commands verified on the device (view, exact reply,
  verified/rejected/unverified status), the terminal behaviour a client must handle, lessons learned
  from production incidents, and sanitised terminal captures to build simulator replies from.
- `docs/portal/`: how the built-in captive portal serves pages and accepts logins, what the
  built-in customisation options and a custom zip can and cannot do, and the Arabic/English
  AFZ Systems login page with its build script.

### Fixed

- The Management Devices tab no longer offers web access. Binding `http acl` also filters the
  router's built-in captive portal, so every client outside the ACL stopped getting the login
  page. The tab now warns, with the removal command, when `http acl` is set while the portal is
  enabled.
- Adding a device is refused while the shared MAC password is still the default placeholder,
  which previously created accounts the router rejected and then blocked.
- Passwords in `password cipher` commands are masked in the command log and
  `ar730_session.log`.

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

[1.0.0]: https://github.com/AFZ92/huawei-ar730-router-easy-manager/releases/tag/v1.0.0
