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
  command. The test simulator reproduces the pause (`harness/paramiko.py` `_Channel`), and a test adds
  three devices in a row.

<a id="L3"></a>
## 3. Route tracking ignores TCP probes

- **Symptom:** a route tracked by `nqa … test-type tcp` stayed `Active` for two minutes, while
  `display nqa history` showed only `timeout`.
- **Verified by:** probe t1tcp pointing at `192.0.2.1:443` kept the route Active. Probe t1icmp at
  the same address made it `State: Invalid Adv Relied, Flags: R` within about a minute.
- **Rules:**
  - Bind default routes to **ICMP** probes (`w1icmp…w5icmp`, `frequency 15`, `timeout 2`,
    `probe-count 3`). Frequency 10 triggers `recommended that the frequency be greater than 14`.
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
