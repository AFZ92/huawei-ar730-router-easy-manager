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
