# AR730 command reference (as verified on the device)

Router: Huawei AR730, VRP **V300R024C00SPC100**, reached over SSH.

This file lists only commands whose syntax or reply we have **seen on the real router**, plus a
clearly marked list of commands still unverified. Raw output is in [`captures/`](captures/). Read
[`terminal-behaviour.md`](terminal-behaviour.md) first: prompts, error formats, Y/N questions and
the `?` pitfall.

Status legend:

- ✅ verified: the reply is captured.
- ⛔ this exact form is **rejected**.
- ❓ used or planned, but the reply has not been captured yet.

`HOST` stands for the hostname and `MAC12` for a MAC address written as 12 lowercase hex digits
(`00e0fc123456`). `MACD` is the dashed form (`00e0-fc12-3456`).

---

## 1. Session and housekeeping

| Command | View | Status | Reply / notes |
|---|---|---|---|
| `screen-length 0 temporary` | user | ✅ | `Info: The configuration takes effect on the current user terminal interface only.` |
| `system-view` | user | ✅ | `Enter system view, return user view with Ctrl+Z.` |
| `system-view` | system | ✅ | Rejected: `Error: Unrecognized command`, because you are already there. |
| `quit` | user | ✅ | **Ends the session**: `Info:Configuration console exit, please retry to log on` |
| `return` | any | ✅ | Silent; back to `<HOST>`. |
| `save` | user | ✅ | Y/N question, then `Configuration file had been saved successfully` and `Note: … after being activated` (normal). |
| `display startup` | user | ✅ | `Startup saved-configuration file: flash:/vrpcfg.zip`. The `Next startup …` line is the same file. |
| `display cpu-usage` | user | ✅ | `CPU Usage: 19.7%  Max: 36.8%` block, then a process table. |
| `display memory-usage` | user | ✅ | `Memory Using Percentage Is: 36%` |
| `display this` | config view | ✅ | Shows the current view's configuration, with the `[V300R024C00SPC100]` header (seen in the mac-access-profile view). |
| `dir flash:` | user | ✅ | `Idx Attr Size(Byte) Date Time(LMT) FileName`, then `613,304 KB total available (198,276 KB free)` |
| `dir flash:/logopath/` | user | ✅ | Empty directory: `Info: File can't be found in the directory` |

## 2. AAA, MAC accounts, portal accounts

### Reading

| Command | Status | Reply / notes |
|---|---|---|
| `display local-user` | ✅ | Table `User-name State AuthMask AdminLevel`. State is `A` (active) or `B` (blocked). AuthMask: `X` MAC/802.1x, `W` web/portal, `MSH` admin, `SH` ssh+http. Long names are truncated (`accampus@domain_...`). The last line is `Total N user(s)`. |
| `display local-user username MAC12` | ✅ | Key/value block. A **blocked** account shows `State : block` and `Block-time-left : 4 Min(s)`. An **active** one shows `Retry-interval` and `Retry-time-left : 2`. `Last login time : -` means it never logged in. There is no description field. |
| `display current-configuration configuration aaa` | ✅ | Per account: `local-user X password cipher …` / `privilege level 0` / `service-type 8021x\|web` / `user-group G` |
| `display current-configuration configuration aaa \| include service-type 8021x` | ✅ | One line per MAC account. |
| `display saved-configuration \| include service-type 8021x` | ✅ | Same, from the saved configuration (compare the two to find unsaved changes). |
| `display current-configuration \| include mac-authen` | ✅ | `access-domain macwhitelist mac-authen force` and the profile's `mac-authen username macaddress format without-hyphen password cipher %^%#…%^%#` |
| `display current-configuration configuration mac-access-profile` | ✅ | `mac-access-profile name m_wl` (with the mac-authen line) and `mac-access-profile name mac_access_profile` (empty). |
| `display domain name macwhitelist` | ✅ | `Authentication-scheme-name : local_auth`. MAC accounts are local, named by bare MAC12 (no `@domain`). |
| `display user-group` | ✅ | `ID Group name User-num`, e.g. `0 grp_managers 22`. |
| `display access-user` | ✅ | `UserID Username IP address MAC Status`. A MAC-authenticated device has Username = MAC12, MAC = MACD and Status `Success`. |
| `display access-user mac-address MACD` | ✅ | Detail block. The MAC may be typed in upper case. Key fields: `User name` (MAC12 = MAC auth attempted), `User vlan event : Pre-authen` (not yet authenticated), `Dynamic service scheme : sch_preauth`, `User authentication type : No authentication`, `User access Interface`, `QinQVlan/UserVlan : 0/20`. |

### Changing

| Command | View | Status | Reply / notes |
|---|---|---|---|
| `local-user MAC12 state active` | aaa | ✅ | Silent. Clears a block. |
| `local-user MAC12 password cipher PW` | aaa | ✅ | `Info: After changing the rights (including the password, access type, FTP directory, bind IP, and level) of a local user, the rights of users already online do not change. …` (success). |
| same command in **user** view | user | ⛔ | `Error: Unrecognized command found at '^' position.` |
| `mac-access-profile name m_wl` | system | ✅ | Enters `[HOST-mac-access-profile-m_wl]`. |
| `mac-authen username macaddress format without-hyphen password cipher PW` | mac-access-profile | ✅ | `Info: The password should meet the complexity check requirement.` This is **accepted**. Confirm with `display this`: the cipher text changes. |
| MAC account creation (app): `local-user MAC12 service-type 8021x` / `password cipher PW` / `user-group G` | aaa | ✅ (via app) | The order matters. The password must equal the profile's shared password, otherwise the device is rejected and the account **blocks itself** after repeated failures. |
| `cut access-user user-id N` | — | ❓ | Used by the app to drop a session; reply not captured in these sessions. |
| `local-user MAC12 ?` | aaa | ❓ | Would list the account attributes; asked but not run. |

## 3. Internet lines: interfaces, routes, NQA

### Reading

| Command | Status | Reply / notes |
|---|---|---|
| `display ip interface brief` | ✅ | `Interface IP Address/Mask Physical Protocol`; `up(s)` = spoofing (loopback/NULL). |
| `display interface brief` | ✅ | `PHY Protocol InUti OutUti inErrors outErrors`; `(v)` marks a VirtualPort. |
| `display interface GigabitEthernet0/0/9` | ✅ | `Description:WAN1`, `Speed :  100,` / `Duplex: FULL`, `Last physical up/down time`, `Last 300 seconds input rate`, `CRC: 115`, `Total Error`. |
| `display interface Vlanif103` | ✅ | State, description and IP only (no counters, utilisation `--`). The physical port comes from `display vlan`. |
| `display vlan 103` | ✅ | `Untagged Port: GigabitEthernet0/0/3` (access). VLAN 20 shows `Tagged Port: GigabitEthernet0/0/2` (trunk). |
| `display ip routing-table 0.0.0.0 0 verbose` | ✅ | One block per default route. See the route states below. |
| `display ip routing-table 149.112.112.112` | ✅ | Short table; shows which next hop a probe address really uses. |
| `display current-configuration \| include ip route-static` | ✅ | `ip route-static 0.0.0.0 0.0.0.0 192.168.1.1 track nqa admin w1icmp` |
| `display current-configuration configuration nqa` | ✅ | `nqa test-instance admin NAME` / `test-type` / `destination-address ipv4` / `frequency` / `timeout` / `probe-count` / `start now` |
| `display nqa results test-instance admin NAME` | ✅ | Up to 5 blocks `N . Test K result The test is finished` with `Completion:success\|failed`, `Destination ip address:`, `Min/Max/Average Completion Time: a/b/c`, `Lost packet ratio: 0 %`. |
| `display nqa history test-instance admin NAME` | ✅ | `Index T/H/P Response Status Address Time`, e.g. `14  102/1/1  2000ms timeout  192.0.2.1 …` |
| `display current-configuration \| include dns` | ✅ | `dns server 8.8.8.8`, `dhcp server dns-list 1.1.1.1 8.8.8.8`, … |
| `display ip pool` | ✅ | One summary per pool: Lease, Network, `Address Statistic: Total/Used/Idle/Expired/Conflict/Disabled`. |

**Default-route states** (in `display ip routing-table 0.0.0.0 0 verbose`):

| What happened | `State:` | `Interface:` | `Flags:` |
|---|---|---|---|
| line in rotation | `Active Adv Relied` | the WAN interface | `RD` |
| port physically down | `Invalid Adv` | `Unknown` | *(empty)* |
| **ICMP probe failed (withdrawn by track)** | `Invalid Adv Relied` | the WAN interface | `R` |

The `Age:` field restarts when a route changes state. Two equal-preference (60) active default
routes share the load.

### Live measurement

| Command | Status | Reply / notes |
|---|---|---|
| `ping -c 20 192.168.1.1` | ✅ | `Reply from …: bytes=56 Sequence=1 ttl=64 time=1 ms`, then `--- statistics ---`, `0.00% packet loss`, `round-trip min/avg/max = 1/1/1 ms` |
| `ping -c 5 -nexthop 192.168.4.1 8.8.8.8` | ✅ | Forces the probe through one line. `-nexthop` takes `IP_ADDR<X.X.X.X>`. |
| `ping -nexthop q` | ⛔ | `Error: Wrong parameter found at '^' position.` |

### NQA probes and tracked routes

| Command | View | Status | Reply / notes |
|---|---|---|---|
| `nqa test-instance admin NAME` | system | ✅ | Creates the probe or enters it: `[HOST-nqa-admin-NAME]` |
| `test-type icmp` / `test-type tcp` | nqa | ✅ | Silent. The supported types (`test-type ?`) are dhcp dns ftp http icmp icmpjitter jitter lspping lsptrace snmp tcp trace udp vpls*. |
| `destination-address ipv4 A.B.C.D` | nqa | ✅ | Silent. |
| `destination-port 443` | nqa | ✅ | `Warning: The specified port is a well-known port, and it is possible to conflict.` (accepted) |
| `frequency 10` + `timeout 2` on **icmp**, then `start now` | nqa | ✅ | `Warning: It is recommended that the frequency be greater than 14. Otherwise, the test result may be incorrect.` → use `frequency 15`. |
| `probe-count 3`, `start now`, `undo start` | nqa | ✅ | Silent. |
| probe settings pasted in **system** view | system | ⛔ | `Error: Unrecognized command` on every line (they belong inside `nqa test-instance`). |
| `undo nqa test-instance admin NAME` while running | system | ⛔ | `Error: The test is in progress, it cannot be deleted.` Run `undo start` inside the probe first; then it is silent. |
| `ip route-static 0.0.0.0 0.0.0.0 GW track nqa admin NAME` | system | ✅ | Silent. `track ?` offers `bfd-session efm-state nqa route-monitor-group`. |
| `undo ip route-static 0.0.0.0 0.0.0.0 GW` | system | ✅ | Silent; removes that default route (with its track). |
| `ip route-static A.B.C.D 255.255.255.255 GW` / `undo …` | system | ✅ | Silent (pins a probe address to one line). |
| `undo ip route-static 0.0.0.0 0.0.0.0 GigabitEthernet0/0/9 dhcp` | system | ✅ | Silent. |
| `track …` (standalone) | system | ⛔ | `Error: Unrecognized command`: there is no standalone track object on this firmware. |

> **Behaviour that matters:** a route tracked by a **TCP** probe is **never withdrawn**, even
> though `display nqa results/history` shows the probe failing. A route tracked by an **ICMP**
> probe is withdrawn within about a minute. There is one probe per route; probes cannot be
> combined. Tested 2026-09-14; see [lessons-learned.md](lessons-learned.md#L3).

## 4. Management access for one device (DHCP binding, static ARP, ACL, web)

### Reading

| Command | Status | Reply / notes |
|---|---|---|
| `display acl 2999` | ✅ | `Basic ACL 2999, 3 rules` / `MGMT-ACCESS` / `Acl's step is 5` / ` rule 5 permit source 10.0.1.0 0.0.0.255 (38 matches)` / ` rule 3000 deny (180 matches)` |
| `display acl all` | ✅ | `Total quantity of nonempty ACL number is 10`, then every ACL. Advanced ACL rules read `rule 5 permit ip destination …`. An interface-bound ACL is titled `Advanced ACL GigabitEthernet0/0/9 3999, 1 rule`. |
| `display current-configuration interface Vlanif20` | ✅ | `description GW-STAFF`, `ip address 10.0.20.1 255.255.254.0`, `authentication-profile p_nac`, `dhcp select interface`, lease, dns-list, and each `dhcp server static-bind …` |
| `display current-configuration \| include static-bind` | ✅ | ` dhcp server static-bind ip-address 10.0.21.254 mac-address MACD description NAME`; prints nothing if there are none. |
| `display current-configuration \| include arp static` | ✅ | `arp static 10.0.21.254 MACD vid 20 interface GigabitEthernet0/0/2` |
| `display current-configuration \| include http` | ✅ | `http acl 2999`, `http server enable`, `http secure-server enable`, `http server permit interface Vlanif1 Vlanif20`, `portal local-server http port 8080` |
| `display current-configuration \| include acl` | ✅ | `acl number N`, ` http acl 2999`, ` acl 2999 inbound` (vty, twice), ` acl-id 3010` |
| `display arp static` | ✅ | Header + `Total:0 Dynamic:0 Static:0 Interface:0` when empty. |
| `display arp interface Vlanif20` | ✅ | Two lines per entry: `10.0.20.53  MACD  17  D-0  GE0/0/2` and then `20/-` on the next line. The gateway entry has type `I -`. |
| `display ip pool interface Vlanif20 used` | ✅ | Pool summary, `Network section Start End Total Used Idle(Expired) Conflict Disabled`, then `Index IP Client-ID Type Left Status`. A lease is `… DHCP 604599 Used`; a binding is `249 10.0.20.250 aabb-ccdd-eeff DHCP - Static-bind`. |
| `display dhcp static user-bind all` | ✅ | `Info: The number of static bind-table is zero.` Captured only **before** any binding existed. It is most likely the snooping/user-bind table and not the server static-bind list, so do not use it to detect `dhcp server static-bind`. Use the configuration or `ip pool … used` instead. |

### Changing

| Command | View | Status | Reply / notes |
|---|---|---|---|
| `dhcp server static-bind ip-address IP mac-address MACD` | Vlanif | ✅ | Silent. The only option after the MAC is `description TEXT` (`?` shows `description`, `<cr>`). |
| same, while that MAC holds a lease on **another** address in the pool | Vlanif | ⛔ | `Error: This MAC address uses another IP address in the ip pool.` Release the lease first ↓ |
| `reset ip pool interface Vlanif20 OLD_IP` | user | ✅ (via app) | Y/N warning, then silent. Frees the lease; the device picks up the bound address when it reconnects. |
| `undo dhcp server static-bind ip-address IP mac-address MACD` | Vlanif | ⛔ | `Error:Too many parameters found at '^' position.` (the caret is under `mac-address`) |
| `undo dhcp server static-bind ip-address IP` | Vlanif | ❓ | The form implied by the error above; the app uses it. Success not yet captured. |
| `arp static IP MACD` | system | ✅ | Silent (`?` after the MAC lists `vid vni vpn-instance <cr>`). |
| `arp static IP MACD vid 20` | system | ⛔ | `Error:Incomplete command`: `vid` requires `interface`. |
| `arp static IP MACD vid 20 interface GigabitEthernet0/0/2` | system | ✅ (via app) | Silent. |
| `undo arp static IP` / `undo arp static IP MACD` | system | ❓ | The app tries the IP-only form first and then the MAC form. Neither reply has been captured. |
| `acl number 2999` | system | ✅ | Enters `[HOST-acl-basic-2999]`. |
| `rule 100 permit source 10.0.21.254 0` | acl-basic | ✅ (via app) | Silent. Rule IDs range over `0-4294967294`; keep them below the final `rule 3000 deny`. |
| `http acl 2999` | system | ✅ (via app) | Silent. It accepts basic ACLs only: `INTEGER<2000-2999>`. ⚠️ **It also filters the built-in portal server (10.0.255.1:8080).** Clients outside the ACL get no captive portal at all (confirmed 2026-09-15, see lessons-learned L13). Do not use it while the portal is in use. |
| `undo http acl` | system | ✅ | Silent. The `http acl` line disappears from the config, and the portal works again for all clients. |
| `http server permit interface Vlanif1 Vlanif20` | system | ✅ (via app) | `Info: Successed in setting web permit interface.` (Huawei's spelling). **It replaces the whole list** (verified 2026-09-15: `http server permit interface Vlanif1` after `Vlanif1 Vlanif20` left only `Vlanif1`), so always list every wanted interface. |

SSH is limited by `acl 2999 inbound` under `user-interface vty`. Management ACLs match source IP
only, which is why a device is pinned by DHCP binding + static ARP (anti-spoofing) and not by MAC.

## 5. Portal local server and SFTP

| Command | View | Status | Reply / notes |
|---|---|---|---|
| `display portal local-server` | user | ✅ | `server ip : 10.0.255.1`, `authentication method : chap`, `protocol : http`, `server port : 8080`, `session-timeout : 8(h)`, `server page-text/policy-text/logo/ad-image : -`, `server background-image : default-image0`, `server pagename : -` |
| `display current-configuration \| include portal` | user | ✅ | `portal local-server ip 10.0.255.1`, `… http port 8080`, `… server-source all-interface`, `portal-access-profile name p_portal` + ` portal local-server enable layer3`, `access-domain portalusers portal force`, `portal captive-bypass enable` |
| `portal local-server ?` | system | ✅ | `ad-image authentication-method background-color background-image http https ip keep-alive load logo page-text policy-text server-source syslog-limit timer url` (`undo portal local-server ?` lists the same) |
| `portal local-server logo load ?` | system | ✅ | `STRING<5-64> Logo file(type:jpg/png, size(px):591*80)` |
| `portal local-server background-image load ?` | system | ✅ | `STRING<5-64> Background image(type:jpg/png, size(px):1366*768)` and `default-image1` |
| `portal local-server ad-image load ?` | system | ✅ | `STRING<5-64> Advertisement image file(type:jpg/png, size(px):670*405)` |
| `portal local-server page-text load ?` / `policy-text load ?` / `load ?` | system | ✅ | `STRING<1-64> [drive][path][file name]` or `flash:` |
| `portal local-server background-color ?` | system | ✅ | `STRING<7> … (Range:#000000-#FFFFFF, Example:#EEEEEE)` |
| `portal local-server url ?` | system | ✅ | `STRING<1-64> Specify Portal local server's URL` |
| `portal local-server page-text load flash:/welcome.txt` (same for `policy-text`, `logo`) | system | ✅ | `Info: The loading process may take a few seconds.Please wait for a moment.` / `Info: Load web file successfully.` / `Warning: The configuration will not take effect and lost after you delete file and reboot.` → **keep the file on flash**. |
| `portal local-server load flash:/portal_ar_v3.zip` | system | ✅ | When the portal is in use it first asks `Warning: Portal local server has been enabled, and this operation will affect online user, continue?[Y/N]:`, then `Info: The loading process…` / `Info: Load web file successfully.` / the keep-file warning. The router then serves **only the files inside the zip**. |
| `undo portal local-server load` | system | ✅ | `Info: The operation will load the default web file. Please wait for a moment..` / `Info: Load web file successfully.` / keep-file warning. Back to built-in pages; `display portal local-server` shows all options `-`. |
| `undo portal local-server page-text load` (etc.) | system | ❓ | Not yet run. |
| `display ssh server status` | user | ✅ | `SFTP Server :Disable\|Enable`, `Stelnet server :Enable`, `Scp server :Disable`, ciphers `aes128-ctr aes192-ctr aes256-ctr`, mac `hmac-sha2-256` |
| `display ssh user-information` | user | ✅ | `admin  password  null` |
| `display current-configuration configuration service-scheme` | user | ⛔ | `Error: Unrecognized command` (service-scheme lives under `aaa`; see `display current-configuration configuration aaa`). |
| `display current-configuration \| include captive\|https-redirect\|free-rule` | user | ✅ | `authentication https-redirect enable`, `portal captive-bypass enable`, `free-rule-template name default_free_rule` + ` free-rule N destination ip X mask 255.255.255.255 source ip any` (pre-auth allows only 10.0.255.1, 10.0.20.1, 10.0.10.1, 1.1.1.1, 8.8.8.8). |
| `undo portal captive-bypass enable` / `portal captive-bypass enable` | system | ✅ | Both silent. Effect on phones not yet established. |
| `sftp server enable` | system | ✅ | `Info: Succeeded in starting the SFTP server.` (undo: `undo sftp server enable` ❓) |
| `display current-configuration \| include ssh` | user | ✅ | `local-user admin service-type terminal ssh http`, `ssh server permit interface all`, `ssh client first-time enable` |

**SFTP from a computer** (`sftp admin@10.0.20.1`) ✅ works with the admin password:

- The remote root `/` **is** `flash:/`. `put file` lands in `flash:/file`.
- Quirk: `ls -l a b c` lists only the first file, and dates show as `Jan 13 1970`. Trust
  `dir flash:` on the CLI instead.
- The built-in portal pages are **not** on flash; the firmware generates them.

For the portal's HTTP behaviour (URLs, login form contract, what a custom zip can and cannot do)
see [`../portal/README.md`](../portal/README.md).
