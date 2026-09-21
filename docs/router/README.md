# Router knowledge base

This is what we know **for certain** about the Huawei AR730 this project manages (VRP
V300R024C00SPC100). It was gathered on the production router so that nobody has to repeat the
experiments. Read it before writing code that sends a command, and before asking the user to
run anything.

| File | Use it for |
|---|---|
| [terminal-behaviour.md](terminal-behaviour.md) | prompts, views, how replies end, error formats, Y/N questions, the `?` and paste pitfalls |
| [command-reference.md](command-reference.md) | every command we have run, with its view, exact reply and status (✅ verified / ⛔ rejected / ❓ unverified) |
| [lessons-learned.md](lessons-learned.md) | problems we hit, their proven causes, and the rules that came out of them |
| [captures/](captures/) | raw terminal output (sanitised) to copy from when building simulator replies or parsers |
| [../portal/README.md](../portal/README.md) | the built-in captive portal: HTTP behaviour, login contract, custom page |

## The network in one paragraph

- **User VLANs with MAC/NAC authentication:**
  - VLAN 10 managers, `10.0.10.1/24`.
  - VLAN 20 staff, `10.0.20.1/23`, carried on trunk `GigabitEthernet0/0/2`.
- **Management:**
  - Vlanif1 `10.0.1.1/24` is the emergency port.
  - SSH is limited by `acl 2999`. Web is limited by `http acl 2999` plus `http server permit interface`.
- **Trusted devices:** local accounts named by MAC (`service-type 8021x`), all sharing the password in
  `mac-access-profile m_wl`, domain `macwhitelist`.
- **Guests and staff without trusted devices:** use the built-in portal at `10.0.255.1:8080`, with
  local `service-type web` accounts in domain `portalusers`.
- **Internet:** up to five lines, WAN1–WAN5, each with a default route tracked by an ICMP NQA probe
  `wNicmp`. An unbound TCP 443 probe `wNtcp` per line detects exhausted quotas.

## Keeping the simulators honest

The application ships two fake routers:

- `_DemoDevice` / `_DemoMgmt` / `_DemoWan` in `ar730_manager.py` provide the offline router
  used by Qt `--demo` and `harness/run_qt_test.py`.

A behaviour belongs in a simulator **only after** it has been seen on the device and recorded here.
When you add one, copy the reply text from `captures/`, not from memory.

Real behaviours the simulators should reproduce. Most already do; check the simulator before a new
test relies on one:

1. The `[V300R024C00SPC100]` header, then a pause, before `display current-configuration` output.
2. Errors: a caret line, then the exact `Error:` wording, with its inconsistent spacing.
3. `save` and `reset ip pool` ask `[Y/N]`.
4. Info replies that are successes: password complexity, local-user rights change,
   `Successed in setting web permit interface`.
5. A MAC account whose password does not match the profile becomes `B` (blocked).
6. `dhcp server static-bind` is refused while the MAC holds another lease in the same pool.
7. `undo dhcp server static-bind … mac-address …` fails with `Too many parameters`.
8. `arp static … vid N` without `interface` is `Incomplete`.
9. A route tracked by a TCP probe is not withdrawn; with an ICMP probe it is.

Real replies that no simulator produces yet (as of 2026-09-15), worth adding if a feature depends on
them:

- the `local-user … password cipher` Info text;
- `The test is in progress, it cannot be deleted.`;
- the NQA `well-known port` and `frequency be greater than 14` warnings;
- anything about the portal local server.

## Still unverified on the device

These appear as ❓ in the command reference. Capture them once and move them to ✅:

- `undo dhcp server static-bind ip-address IP` (expected to be the correct removal form)
- `undo arp static IP` and `undo arp static IP MAC`
- whether `POST /logout` from a custom portal page really ends the session
- `local-user MAC12 ?` (is there any description attribute?)
