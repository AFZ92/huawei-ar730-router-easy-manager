# Lessons learned on the real AR730

Each entry records a symptom, the verified cause, and the rule we follow now. They come from
working sessions against the production router (VRP V300R024C00SPC100) on 2026-09-14 and
2026-09-15. The evidence is in [`captures/`](captures/).

---

<a id="L1"></a>
## 1. A MAC account that "was added" but the device never gets on

- **Symptom:** the account exists (`display local-user` lists it), but the device is refused. The
  account shows `State B` with `Block-time-left: 4 Min(s)`, and `Last login time: -`.
- **Cause:** the account password did not match the shared password in `mac-access-profile m_wl`.
  The app had used its placeholder `CHANGE-ME-SHARED-MAC-PASSWORD`. Each failed authentication counts
  down `Retry-time-left`, and the router then blocks the account on its own.
- **Rules:**
  - Never create a MAC account while the shared password is the placeholder (the app refuses).
  - After every refresh, read `display local-user` and flag `B` accounts.
  - The router cannot show a password. To learn "the current password", set a known new one:
    first in the profile (`display this` must show a different cipher), then on **every** MAC account
    in the same session, then `save`. Sessions already online are not affected.
  - `local-user X state active` unblocks, but the block returns while the password is still wrong.

<a id="L2"></a>
## 2. "Commands executed but the device did not appear" (several adds in one session)

- **Symptom:** the app reported a failed verification. The device actually worked, and the log had
  merged lines such as `>>> aaasystem-view`.
- **Cause:** `display current-configuration` prints `[V300R024C00SPC100]` and then pauses. The
  prompt regex treated that header as a `[HOST]` prompt, returned early, and every following reply
  shifted by one command.
- **Rules:** match the prompt by the **hostname** from the banner, and drain stale bytes before each
  command. The offline router simulator reproduces the pause (`_DemoChannel` in `ar730_manager.py`), and a test adds
  three devices in a row.

<a id="L3"></a>
## 3. Route tracking ignores TCP probes

- **Symptom:** a route tracked by `nqa … test-type tcp` stayed `Active` for two minutes, while
  `display nqa history` showed only `timeout`.
- **Verified by:** probe t1tcp pointing at `192.0.2.1:443` kept the route Active. Probe t1icmp at
  the same address made it `State: Invalid Adv Relied, Flags: R` within about a minute.
- **Rules:**
  - Bind default routes to **ICMP** probes (`w1icmp…w5icmp`, `frequency 15`, `timeout 2`).
    Frequency 10 triggers `recommended that the frequency be greater than 14`. The 3 probes per
    test are the **default**: `probe-count 3` was typed once but never shows up in
    `display current-configuration configuration nqa`, which prints non-default values only.
  - Keep **TCP 443** probes (`w1tcp…w5tcp`) unbound. Their only job is to reveal an exhausted ISP
    quota: ping still answers, but HTTPS fails. The app reads them and can take the line out of rotation.
  - A running probe cannot be deleted: send `undo start` inside it first.
  - After changing a probe, wait **at least 60 s** (several `frequency` cycles) before judging
    whether the route reacted. Two early tests were inconclusive because they were read after
    about 28 s.
  - NQA completion times were several times higher than a real ping (≈300 ms against 44 ms). Use
    `ping -c N -nexthop GW DEST` for latency, and NQA only for up/down.

<a id="L4"></a>
## 4. Probe routes can drag client DNS onto one line

- **Found while investigating** WAN1's exhausted quota (the ISP blocks browsing without cutting the
  link, so ping still works).
- **Cause:** DHCP gives clients `1.1.1.1` and `8.8.8.8` as DNS servers. Those same addresses had
  been pinned to single lines with `/32` static routes for the probes (8.8.8.8 via WAN1). Every
  client DNS query to 8.8.8.8 therefore left through WAN1, blocked or not, whichever line carried
  the rest of the traffic.
- **Rules:**
  - A probe address must **never** be one that clients use (DNS or otherwise). Current probe
    addresses: WAN1 149.112.112.112, WAN2 94.140.14.14, WAN3 9.9.9.9, WAN4 8.8.4.4, WAN5 1.0.0.1.
  - Each probe address needs a `/32` route through **its own** line. Check with
    `display ip routing-table <probe>`. The original config probed WAN1 via 1.1.1.1, whose route
    left through WAN2, so WAN1's health really measured WAN2.
  - Remove untracked `ip route-static 0.0.0.0 0.0.0.0 <port> dhcp` routes. An untracked default
    route keeps a dead line in rotation.

<a id="L5"></a>
## 5. `?` help lines can execute commands

- **Symptom:** after pasting a list of "help only" lines, a real `arp static 10.0.20.250
  aabb-ccdd-eeff` and a real `dhcp server static-bind … 10.0.20.250` existed on the router.
- **Cause:** after printing help, VRP puts the command back on the input line. The next pasted
  newline submits it, and a **complete** command (its help listed `<cr>`) runs.
- **Rules:**
  - Send `?` only on incomplete stems.
  - Give one `?` per step, and tell the user to clear with `Ctrl+U` before the next line.
  - Never include a complete command followed by `?` in a pasted block.
  - Assume any test values used this way may now be configured, and check.

<a id="L6"></a>
## 6. Pasting drops the first character

- **Symptom:** `isplay …` → `Error: Unrecognized command`, five times in one session.
- **Rules:** tell the user to press Enter before pasting. When reading their output, check each
  command echo before trusting "no reply" as an empty result.

<a id="L7"></a>
## 7. Typing configuration in the wrong view

- **Symptom:** every `local-user …` line was `Unrecognized`, and then `quit` closed the SSH session.
- **Cause:** the `system-view` and `aaa` lines had not been applied, so the rest ran in user view.
- **Rules:** give commands in blocks that begin by entering the view, and state the prompt the user
  must see (`[HOST-aaa]`). Stop at the first `Error:` and do not `save`.

<a id="L8"></a>
## 8. Binding a MAC that already holds a lease

- **Symptom:** `dhcp server static-bind ip-address 10.0.21.254 mac-address …` →
  `Error: This MAC address uses another IP address in the ip pool.`
- **Rules:**
  - Free the old lease first with `reset ip pool interface VlanifN OLD_IP` (user view, Y/N),
    then bind.
  - The device gets the new address only after it reconnects or renews.
  - Only leases in the **same** pool matter. A lease on another VLAN is left alone.

<a id="L9"></a>
## 9. `undo` does not always mirror the add command

- `undo dhcp server static-bind ip-address IP mac-address MAC` →
  `Error:Too many parameters` (the caret is under `mac-address`). Use
  `undo dhcp server static-bind ip-address IP`. That success has not been captured yet.
- `undo arp static …` has not been captured in any form yet. The app tries the IP-only form and
  then the IP+MAC form.
- **Rule:** before relying on any `undo`, capture its reply once on the device, then add it to
  [command-reference.md](command-reference.md) and to the simulators.

<a id="L10"></a>
## 10. Management access is by IP, never by MAC

- `acl 2999` (vty inbound and `http acl`) matches **source IP** only.
- To let one device on a user VLAN manage the router, we:
  1. pin its IP with a DHCP static binding;
  2. stop spoofing with `arp static IP MAC vid V interface PORT` (`vid` without `interface` is
     `Incomplete`);
  3. add `rule N permit source IP 0` **before** `rule 3000 deny`;
  4. ~~for web access, `http acl 2999` plus `http server permit interface Vlanif1 VlanifN`~~.
     **Do not do this:** `http acl` also blocks the captive portal (see [L13](#L13)). Management
     devices use SSH; the web stays limited to `http server permit interface Vlanif1`.
- The device must still be a trusted (MAC-authenticated) device on a NAC VLAN. It must also use
  **its own VLAN's gateway** (`10.0.20.1`), because the staff ACL denies other internal subnets.
- Never remove `rule 5` (the emergency `10.0.1.0/24` port) or the rule of the address you are
  connected from.

<a id="L11"></a>
## 11. Built-in portal: what can and cannot be customised

This entry is summarised here; the full account is in [`../portal/README.md`](../portal/README.md).

- `page-text` and `policy-text` load fine (UTF-8 Arabic displays correctly). The built-in page
  opens the welcome text in a **pop-up**, which browsers block, so it "does not appear".
- `portal local-server load X.zip` replaces **all** pages, and the router then serves only the zip's
  files (a missing `auth_success.html` gave a blank page after login).
- The built-in `auth_success.html` is filled in by the firmware (user, IP, login time). Custom
  pages are served **as is**, so those values stay empty, and a custom page cannot know the client
  IP.
- With a custom zip, `POST /logout` answered **404** in our test from the Mac. Whether it still logs
  the user out is **not yet verified**.
- **Rule:** if showing the IP and time matters more than the design, keep the built-in pages and
  change only logo, background, colour and the two texts.

<a id="L13"></a>
## 13. `http acl` silently disabled the captive portal for everyone

- **Symptom:** phones on VLAN 20 (Android and iPhone) no longer got the portal page. They sat in
  `display access-user mac-address …` with `User vlan event : Pre-authen`,
  `Dynamic service scheme : sch_preauth` and `No authentication`. Reverting to the built-in pages
  (`undo portal local-server load`) did not help, and toggling `portal captive-bypass` did not help.
  From the Mac (10.0.21.254) the portal pages still loaded fine.
- **Cause:** the Management Devices feature had added `http acl 2999`. That ACL permits only
  10.0.1.0/24, 10.0.10.0/24 and the management device's /32, and the router applies it to the
  **portal local server on port 8080 as well** as to web management. Every other client was refused.
  The Mac was allowed, which hid the problem during portal testing.
- **Proof (both directions):** `undo http acl` → the portal page appeared on phones immediately; re-applying `http acl 2999` → it disappeared again.
- **Rules:**
  - Never bind `http acl` while the built-in portal is in use.
  - Restrict web management with `http server permit interface` only. Unlike the ACL, that did not
    affect the portal: it worked with both `Vlanif1` and `Vlanif1 Vlanif20`.
  - Test portal changes from a client that is **not** in any management ACL, never only from the
    admin Mac.
  - `portal captive-bypass enable` was present since the first capture (2026-09-14) and is not the
    cause.
  - The app no longer offers web access for management devices, and it warns in the Management
    Devices tab when `http acl` is set while `portal local-server` is configured.

<a id="L14"></a>
## 14. An exhausted quota has two shapes, and the second one is invisible to every probe

- **Symptom:** WAN2 (quota used up) passed both probes — ICMP `success` and TCP 443 `success` —
  yet users called it unusable. The app called it `slow`: 92 ms and **50% loss** in one
  `ping -c 10`, while a manual `ping -c 20` minutes later showed 0% loss and a flat 70 ms.
- **Verified by:** `display nqa history test-instance admin w2icmp` — 13 of 50 probes `2000ms
  timeout` (~26%), spread as 1/3 or sometimes 2/3 per test, never 3/3. `display interface
  GigabitEthernet0/0/8` at the same moment: 121 kbit/s in, 213 kbit/s out, utilisation 0.01%/0.03%,
  `Discard 0`, `Total Error 0`, `CRC 0`.
- **Cause:** the ISP answers an exhausted quota in two different ways.
  - **Blocking** (WAN1, see [L4](#L4)): ICMP passes, HTTPS fails. The TCP 443 probe catches it.
  - **Policing** (WAN2): nothing is blocked; a share of packets is simply dropped upstream. Probes
    that send one small packet mostly get through, so ICMP and TCP 443 both report `success`.
- **Rules:**
  - Loss is the only signal for a policed line, and the port counters cannot show it: the drops
    happen upstream, so `Discard`/`Total Error` stay at zero and utilisation stays near zero.
  - Never read loss from a single `ping -c 10`: on this line the same minute gives 0% or 50%.
    `display nqa history` (50 probes, about 4 minutes) is the stable sample.
  - A running test refuses every parameter change (`Error: The test is in progress, parameters
    cannot be changed.`), `undo` included. Wrap any change in `undo start` … `start now`, and
    remember the tracked route is withdrawn while the test is stopped.
  - `fail-percent` does make the router act, but it **flaps**. Tested on wan2 with
    `fail-percent 30`: every test that lost 1 of 3 probes reported `Completion:failed` and the
    route went `Invalid`, and the next clean test brought it straight back — five readings of
    `display ip routing-table 0.0.0.0 0 verbose` gave Active, Invalid, Active, Active, Active.
    The router has no memory between tests, so it can never decide that a line is *degraded*;
    it only mirrors the last test. Left in place it would move client sessions every 15 s.
  - Making the probe fail *deterministically* instead, by overloading the throttled pipe, is not
    possible either. An ICMP test refuses `interval milliseconds`, so it can offer at most
    `datasize` bytes per second — 64.8 kbit/s at the 8100-byte maximum, below any line's capacity,
    so no queue ever builds. That leaves only a single big packet against `timeout`, whose floor is
    one second: 2 × 8100 × 8 bits in 1 s means the router can only catch a line **below about
    130 kbit/s**. wan2 at 180 kbit/s — unusable, and well under the 2 Mbit/s the user needs —
    passes that test.
  - Therefore: keep the router's track for hard down/up only, and put the degraded-line decision
    in the app, which measures the capacity from the latency of a big `ping -s` and can put its
    threshold wherever the subscription needs it.

<a id="L15"></a>
## 15. Measure a line with a big packet: the 56-byte probe lies

- **Question that started it:** is there an address whose reply is large, so the check is real?
  There is no need for one — an ICMP echo reply carries back the payload it was sent, so `ping -s`
  (and `datasize` inside NQA) decides the size. The default is **56 bytes**, which is why an
  exhausted line still looked perfect.
- **Measured 2026-09-16, same minute, 20 packets each:**

  | Line | 56 bytes | 1400 bytes | Implied pipe |
  |---|---|---|---|
  | wan2, quota used up | 70 ms, 0% loss | 189 ms, 10% loss | ≈ **180 kbit/s** |
  | wan3, healthy | ≈ 50 ms | 54 ms, 0% loss | > 5 Mbit/s |

- **Cause:** the ISP polices an exhausted quota by bytes. A 56-byte probe costs almost nothing and
  sails through, so ICMP, TCP 443 and DNS all report success. A 1400-byte packet has to be
  serialised through the throttled pipe, and the extra delay measures that pipe directly:

      rate_bits_per_sec ≈ 2 × (big_bytes − small_bytes) × 8 ÷ (big_rtt − small_rtt)

  For wan2: 2 × 1344 × 8 ÷ 0.119 s ≈ 180 kbit/s, which matches the 213 kbit/s the port counters
  reported while showing 0.03% utilisation — the line was saturated at its throttled ceiling, not
  at its physical one.
- **Rules:**
  - The delay difference is the signal, not the loss. Loss on the same line read 0%, 10% and 50%
    within minutes; the two latencies were stable to within 2 ms on both lines.
  - Always measure a known-good line in the same minute. Some destinations rate-limit large ICMP
    themselves, and only the comparison tells that apart from a real fault.
  - Do **not** raise `datasize` on the ICMP probe that a route tracks. That probe's only job is
    up/down, and a strict probe would flap the route (see [L14](#L14)).

<a id="L16"></a>
## 16. Three tables see three different networks; only the MAC table sees everyone

- **What we found (2026-09-17):** on VLAN 20 the MAC address table held about 150 entries while the
  ARP table of `Vlanif20` held 26, and the DHCP pool of `Vlanif1` reported 21 leases with `Idle : 0`
  and `Disabled : 232`.
- **Why they differ:**
  - `display mac-address` learns from any frame. A device appears the moment it sends anything, with
    no address and no authentication — so it is the only complete answer to "who is on this VLAN".
  - `display arp interface VlanifN` needs the device to already hold an IP and to have talked to the
    gateway. A device that failed to get an address is invisible here.
  - `display ip pool interface VlanifN used` shows what the router *handed out*, which includes
    devices that have since left (a 7-day lease keeps the address reserved) and excludes devices with
    a static address.
- **Rule:** build the per-VLAN client list from the MAC table, then enrich each MAC with the ARP and
  pool rows. Never start from ARP: it silently hides exactly the devices that are in trouble.
- **Second rule:** a MAC entry is per (MAC, VLAN) pair. The same MAC really does appear under VLAN 1
  and VLAN 20 on this device. Key the table by (MAC, VLAN).
- **Third rule:** a network reaches the router in one of **two shapes**, and the second is invisible
  to everything above. VLANs 1, 10 and 20 are switched: they have a `Vlanif`, member ports, and MAC
  table entries. VLANs 30-70 are routed: they arrive tagged on `XGigabitEthernet0/0/0` and terminate
  on sub-interfaces (`XGigabitEthernet0/0/0.60`, `dot1q termination vid 60`). A sub-interface
  terminates the tag instead of switching it, so **`display vlan 60` shows no port and
  `display mac-address vlan 60` returns 0** while 143 devices are happily leased on it. For such a
  VLAN the client list must come from ARP and the DHCP pool of the sub-interface; the MAC table
  never sees them. Deciding "this VLAN is empty" from the MAC table alone is wrong.
- **Fourth rule:** the VLAN list is not the Vlanif list. Of 13 VLANs only 5 carry an IP interface, so
  the other 8 can show MAC entries and ports but never an address — the UI must say so rather than
  show an empty table.
- **Fifth rule — comparing pools finds the leak.** One MAC holding a lease in two pools at once is
  not a device that moved: a lease survives the move, but on this network 15 of the 21 VLAN 1 leases
  belong to devices that also hold a VLAN 60 lease, which is a standing leak, not history. The cause
  is the trunk to the core switch: VRP permits VLAN 1 on a trunk by default and does not print it,
  so untagged frames land in VLAN 1, and `Vlanif1` hands out management addresses because it runs
  DHCP with no `authentication-profile`. To find it, read `display ip pool interface X used` for
  every network and intersect the MACs; to confirm one device, look at its port in
  `display mac-address vlan 1` — `GE0/0/2` is the trunk, so that row is a leak.
- **Sixth rule — usable is not total.** A pool's capacity is `Total − Disabled`: VLAN 60 reads Total
  254 with 98 disabled by `excluded-ip-address 10.0.60.2 10.0.60.99`, so 155 usable against 143
  used. Judging "there is room" from Total is how a pool runs dry while the numbers look healthy.

<a id="L12"></a>
## 12. Working method with the production router

- The user runs the router commands and pastes the output. Claude may query the portal over HTTP
  from the Mac, read-only (`curl`).
- **No `save` until a change is tested.** An unsaved mistake is undone by a reboot.
- Stage risky changes: create, verify, bind, verify again, then clean up and save.
- Always give the rollback command before the change.
- Mask passwords everywhere: logs, captures, documents.
- When the router's reply to a command is unknown, ask for it before coding against it. Record it
  here, in [command-reference.md](command-reference.md), and in the simulators.
