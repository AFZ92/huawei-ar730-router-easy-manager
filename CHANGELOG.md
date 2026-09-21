# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Qt is now the sole desktop interface and the default for all launchers, builds and demo mode.
  The migration gate, handoff documents and Tkinter-only harnesses were removed; the retained
  AR730 engine continues to provide protocol validation and the offline router simulator.

### Added

- Qt now exposes the remaining production pages: Management Devices, Internet Lines,
  Permission Groups, Settings/Firebase and the masked command log. The new controls use the
  existing router read/write primitives, preserve the manual WAN last-line guard, provide explicit
  confirmation for management and routing changes, and stop the Qt WAN timer on disconnect/close.

- The modern Qt preview can now add a Trusted Device. Its focused Arabic dialog uses the same
  shared AR730 operation as the production Tkinter interface, including MAC validation, the
  required command order, post-write AAA verification, and local audit record.

- Trusted Devices in the Qt preview can now update a selected device's descriptive name and note.
  This edit remains local-only, preserves the selected row, and never sends a router command.

- Trusted Devices in the Qt preview can now change a selected device's permission group. The
  confirmation dialog makes the session cut explicit; the shared AR730 operation re-reads AAA
  before updating the local audit record.

- Trusted Devices in the Qt preview can now revoke a selected device. The dialog records an
  optional reason and makes the irreversible router deletion explicit; the shared operation
  verifies the account is absent before marking the local record revoked.

- Trusted Devices in the Qt preview can now export a UTF-8 CSV compatible with Excel. Its data
  includes active accounts as well as locally archived and missing records, matching the legacy
  table rather than silently dropping them.

- Trusted Devices in the Qt preview now has its own refresh action. It uses the shared read path,
  so it refreshes account states without changing router configuration.

- Portal Accounts in the Qt preview can now update a selected account's descriptive name and note.
  The edit uses the shared local operation, keeps the account selected, and never sends a router
  command. The Qt portal table now also retains revoked and missing local records.

- Portal Accounts in the Qt preview can now export their complete visible data as an Excel-friendly
  UTF-8 CSV, including local archived records.

- Portal Accounts in the Qt preview now has its own read-only refresh action, which reloads
  router account data without changing configuration.

- Portal Accounts in the Qt preview can now add and verify a local web account using the shared
  AR730 operation. The Arabic dialog masks the password and validates account, password, group,
  and duplicate cases before writing to the router.

- Portal Accounts in the Qt preview can now change a selected account password through the shared
  AAA operation. The new password is masked in the dialog and excluded from local activity data.

- Portal Accounts in the Qt preview can now change a selected account's permission group through
  the existing AAA sequence. The dialog makes the required session cut explicit, and the local
  record is updated only after the account group is confirmed by rereading AAA.

- Portal Accounts in the Qt preview can now delete a selected account after an explicit warning.
  The shared operation preserves the legacy AAA sequence, verifies the account is absent, then
  archives the account and optional deletion reason locally.

- The Qt preview now has a dedicated refresh action for the current access-user sessions. It reads
  the live session table only and does not change AAA accounts or router configuration.

- The Qt preview can now disconnect one selected access-user session. The confirmation names the
  affected connection, uses the established AAA command sequence, and re-reads sessions to verify
  the disconnect without changing the account itself.

- The Qt preview can now add a selected live connection to Trusted Devices. MAC, IP, and current
  account are read-only in the dialog; the existing shared device operation verifies AAA, and a
  separate confirmation offers to disconnect the old session only after the account is added.

- The Qt preview now reads the complete router VLAN inventory and the clients of the selected
  network through the existing shared reader. It keeps the legacy distinction between switched
  VLANs, addressed VLAN interfaces, and dot1q subinterfaces, while leaving network selection and
  refresh strictly read-only.

- Clients selected in the Qt network table can now be named locally. The dialog identifies the
  MAC address and makes clear that naming neither changes the router nor makes a device trusted.

- The Qt network table can now scan DHCP pools for cross-network leases using the same read-only
  operation as the legacy interface. Affected rows identify the other VLAN and address, while the
  network context calls out any pool nearing exhaustion.

- The Qt network table can now disconnect one or several selected authenticated clients. It lists
  the affected devices before confirmation, preserves their AAA accounts, and rereads the selected
  network after the established access-user cut sequence.

- Optional Firebase Firestore synchronization: the application always writes its local JSON
  copy first, uploads changes automatically when online, retries each minute while a change is
  pending, and downloads newer shared records on other manager devices. Firebase connection
  details are entered from Settings; leaving them empty retains local-only operation.

- **Clients by Network** tab: a dropdown lists every VLAN the router actually has - not only the
  ones that carry an IP interface - and shows every device on the chosen one with its address,
  MAC, physical port, how it got its address (leased, reserved, static or none at all) and its
  authentication state. The list is built from the router's MAC address table rather than its ARP
  table, so a device that failed to get an address still appears; when devices on a network have
  no address at all, the status bar says how many, which is the first sign of an exhausted address
  pool or a failing authentication. For a VLAN with no IP interface the tab explains why there is
  no pool and no address column instead of showing an empty
  table, and an empty network is explained rather than left blank: either no port on this router
  carries the VLAN, or ports carry it but no traffic crosses the router, which usually means its
  gateway is another device. Networks reached through a dot1q sub-interface (`dot1q termination
  vid N`) are listed too, with their clients read from the sub-interface's ARP table and DHCP pool:
  such a network leaves no trace in the MAC address table at all, so it would otherwise look empty
  while hundreds of devices are using it. Each row also states its **presence** - active (in the
  ARP table), seen on the network (sending frames but holding no address) or address reserved only
  (a lease held by a device that is not here), which separates the devices actually using the
  network from the leases that merely consume its pool - and marks a randomised MAC, the kind
  modern phones generate per network and change between sessions.
- Devices can be **named from the Clients by Network tab** and the name is stored locally against
  the MAC, so it follows the device across networks and address changes. Naming touches the local
  data file only, never the router, and does not make the device trusted. Double-clicking a row
  opens the naming dialog; double-clicking its IP address opens that address in the browser.
- **Disconnect selected** in the same tab: several rows can be selected and their sessions cut in
  one step, after a confirmation that lists the devices by address, MAC and the name you gave them.
  It acts only on networks that carry an `authentication-profile`, because a network without one
  has no session to cut - there the tab says so instead of sending a command that would do nothing.
  A router error on any device is reported rather than swallowed.
- **Vendor names** in the Clients by Network tab, from the three IEEE registries shipped in
  `data/oui.dat` (53,941 assignments, 500 KB). The longest assignment wins, so a small company's
  36-bit block is not mistaken for the 24-bit block it sits inside. A prefix registered without a
  public name is shown as an undisclosed vendor, which is not the same as an unregistered prefix.
  The file is optional: without it the tab falls back to showing the raw prefix.
- **Cross-network scan** in the same tab: one read-only command per network with an IP interface
  reads every DHCP pool at once and compares them. A MAC that holds a lease on two networks is
  listed in a new **Other networks** column, with the address it holds elsewhere, and its row is
  marked - the signature of a network reaching a device untagged over a switch trunk, which is how
  user devices end up taking management addresses. The scan also reports pools close to exhaustion,
  counting the addresses actually available (total minus the range excluded with
  `excluded-ip-address`) rather than the nominal size of the subnet. Nothing is changed on the
  router; the result stays on screen for every network you select afterwards.

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
- Bandwidth measurement per line, which catches an exhausted quota the ISP answers by throttling
  instead of blocking: every probe (ping, HTTPS, DNS) still succeeds because each sends a single
  small packet, so the line is measured again with a 1400-byte ping and the extra round-trip delay
  gives the real capacity. A line under 2 Mbit/s is reported as **Throttled**, with the measured
  figure shown in its own column and both packet latencies in the report.
- Take a line out of rotation and put it back exactly as it was; optional automatic monitoring that
  takes a quota-blocked line out after two failed checks and restores it after two good ones,
  never removing the last working line. A throttled line is taken out the same way, on two
  bandwidth measurements ten minutes apart, and is only put back once a measurement shows at least
  4 Mbit/s again — never on the absence of a measurement.
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
