# AR730 Access Manager

**A desktop GUI for managing network access on Huawei NetEngine AR730 routers — MAC whitelisting, captive-portal accounts, and live sessions — without typing a single VRP command.**

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://github.com/AFZ92/ar730-access-manager/actions/workflows/tests.yml/badge.svg)](https://github.com/AFZ92/ar730-access-manager/actions/workflows/tests.yml)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)](#installation)
[![Offline demo](https://img.shields.io/badge/demo-no%20router%20needed-green.svg)](#try-it-without-a-router)

> 🇸🇦 [اقرأ هذا الملف بالعربية](README.ar.md)

Front-desk staff should not need to know `aaa`, `local-user`, or `cut access-user` to let a
printer onto the network. This tool turns those operations into buttons, enforces the ordering
rules the hardware silently requires, verifies every write by reading the configuration back,
and keeps a local record of *who* a MAC address actually belongs to — something the router
cannot store.

Ships with a **complete offline router simulator**, so you can evaluate and train on it before
it ever touches production hardware.

> **Language note:** the interface ships in **English and Arabic**, with full right-to-left
> layout mirroring in Arabic. Switch languages in the Settings tab.

---

## Table of contents

- [Why this exists](#why-this-exists)
- [Features](#features)
- [Try it without a router](#try-it-without-a-router)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [The rules it enforces for you](#the-rules-it-enforces-for-you)
- [Security model](#security-model)
- [Testing](#testing)
- [Project layout](#project-layout)
- [Building a Windows executable](#building-a-windows-executable)
- [Compatibility](#compatibility)
- [Contributing](#contributing)
- [License](#license)

---

## Why this exists

Huawei VRP is powerful and unforgiving. Configuring one trusted device by hand means getting a
sequence of interdependent commands exactly right, and the failure modes are quiet: a user
account created without a group silently receives **unrestricted access**; a permission change
appears to succeed but does not apply until the session is torn down; a password that happens
to equal the username is rejected with a message that does not explain why.

Every one of those rules cost somebody an afternoon. This tool encodes them so they cost
nobody an afternoon again.

It is deliberately **not** a general-purpose network manager. It does one job — access control
on an AR730 — and it does it in a way a non-engineer can be trusted with.

## Features

| Area | What you get |
|---|---|
| **Trusted devices** | Add and revoke MAC addresses on the whitelist. A registered device joins the network with **no login page** — right for computers, printers, cameras and access points. |
| **Portal accounts** | Create and delete captive-portal accounts, reset passwords, change permission groups. The right path for phones. |
| **Live sessions** | See who is connected, on which IP and MAC, authenticated or pending. Cut any session. Promote a connected device straight into the whitelist with one click. |
| **Permission groups** | List groups with the ACL number bound to each one, and the member count. |
| **Search** | Live filtering across every table by MAC, name, status, group, IP or note. MAC matching ignores separators — typing `00005e00` finds `00:00:5E:00:53:01`. |
| **Local records** | Owner name, note, date added, and revocation reason — the human context the router has no field for. Editable offline, with no SSH connection needed. |
| **Command log** | Every command sent and every reply received, in full. The first place to look when something misbehaves. |
| **Bilingual UI** | English and Arabic, with true RTL layout mirroring — not just translated strings. |
| **Offline simulator** | A built-in fake AR730 that enforces the real device's rules, for evaluation and training. |

### Revocation is not deletion

Revoking a device removes it from the router — access is lost immediately — but the local
record survives, marked revoked, with the date and the reason, shown greyed out. You keep an
audit trail of who had access and when it was withdrawn.

## Try it without a router

No hardware, no `paramiko`, no network:

```bash
python ar730_manager.py --demo
```

The simulator enforces the real constraints: it rejects inverted command ordering, rejects a
password equal to the username, rejects `irreversible-cipher`, and prompts `[Y/N]` on save.
Its data lives in separate files and the title bar reads **DEMO**, so the two modes can never
be confused.

This is where you train a new staff member.

## Installation

Requires **Python 3.9 or newer** with Tkinter.

```bash
git clone https://github.com/AFZ92/ar730-access-manager.git
cd ar730-access-manager
pip install -r requirements.txt
python ar730_manager.py
```

<details>
<summary><b>Platform notes</b></summary>

**Linux** — Tkinter is often packaged separately:

```bash
sudo apt install python3-tk      # Debian / Ubuntu
sudo dnf install python3-tkinter # Fedora
```

**macOS** — the system Python ships **Tk 8.5**, which fails to render on current macOS
releases and produces a blank window. Use a Python built against Tk 8.6 or newer:

```bash
brew install python-tk           # or install Python from python.org
```

The included `run.sh` resolves a suitable interpreter and the Tcl/Tk library paths for you.

**Windows** — the bundled Python installer includes Tkinter; nothing extra is needed.

</details>

## Configuration

Settings live in `ar730_settings.json`, written next to the program on first save.

| Key | Meaning |
|---|---|
| `host` / `port` | Router address. Leave the port box empty to use 22. |
| `username` | SSH user. **The password is never stored** — it is asked for on every launch, by design. |
| `mac_shared_password` | Shared password for MAC-authentication accounts. **Must match the router byte for byte.** |
| `default_mac_group` / `default_portal_group` | Group preselected in the add dialogs. |
| `known_groups` | Groups offered when the router has not been read yet. |
| `ui_lang` | `en` or `ar`. |

> [!IMPORTANT]
> `mac_shared_password` must be identical to the value configured on the router under:
>
> ```
> mac-access-profile name m_wl
>  mac-authen username macaddress format without-hyphen password cipher <value>
> ```
>
> If they differ, no trusted device will ever get on, and the router will report
> `Local username or password is wrong`. This is the single most common cause of
> "I whitelisted it and it still doesn't work".

### Files written next to the program

| File | Contents |
|---|---|
| `ar730_settings.json` | Settings. Never contains the SSH password. |
| `ar730_devices.json` | Owner names, notes, and the historical record. **Back this up.** |
| `ar730_session.log` | A copy of the command log. |

All three are gitignored — they contain live network data.

## Usage

1. Enter the router address, username and password, then press **Connect**.
2. **Online Now** shows current sessions. Select a device you recognise and press
   **Trust This Device** to carry its MAC into the add form.
3. **Trusted Devices** adds a device manually, changes its group, edits its name/note, or
   revokes it.
4. **Portal Accounts** creates accounts for staff and guests.
5. **Command Log** shows exactly what was sent and received.

### Why phones do not belong in the whitelist

Modern phones generate a **random MAC address per network** (the locally-administered bit is
set — addresses like `3e4b…`, `7a2c…`, `0e1f…`). The address changes and the trust breaks.
Give phones a portal account and keep the whitelist for computers, printers, cameras and
access points.

## The rules it enforces for you

These are not cosmetic details. Each one is a real VRP behaviour the tool handles so you
do not have to remember it:

1. **Command order is mandatory** — `service-type`, then `password`, then `user-group`.
   Any other order is rejected with `The normal service type cannot be configured`.
2. **The MAC password is shared and must not equal the username.** The device rejects
   `password cannot be the same as a user name`.
3. **`cipher`, not `irreversible-cipher`.** The latter is refused in this context.
4. **A group is mandatory.** An account with no group gets *unrestricted* access. The tool
   warns before saving without one.
5. **Permission changes do not apply to a live session.** Every group change is followed by
   `cut`, so the device re-authenticates with the new permissions.
6. **Every write is verified.** After each change the configuration is read back and checked.
   Success is never inferred from the absence of an error message.
7. **Saving is automatic.** `save` runs after each successful change, so nothing is lost on
   reboot.

## Security model

- **The SSH password is never written to disk.** It is requested at every launch.
- **Router management should be restricted by ACL** to your management networks. The machine
  running this tool must sit inside one of them.
- **Do not expose SSH to the internet** via `nat static` to widen access. If you need to
  manage the router from outside the office, the correct route is a VPN into the management
  network.
- **`ar730_devices.json` contains personal data** (device owner names). Treat it accordingly
  under your local data-protection obligations.

Found a security problem? See [SECURITY.md](SECURITY.md).

## Testing

The project ships a **headless harness**: a substitute for `tkinter` that implements the real
widget behaviour, plus a simulated AR730 that speaks VRP. The whole application is constructed
and its buttons pressed in the order a member of staff would press them.

```bash
python harness/run_test.py        # 196 checks — full application flow
python harness/run_demo_test.py   #  14 checks — demo mode
```

No display, no router, no network required — which is why it runs in CI on every push.

Coverage includes command ordering, write verification, revocation semantics, search and
filtering, RTL layout mirroring, widget packing order, and window sizing.

## Project layout

```
ar730_manager.py        the entire application — single file, no framework
harness/
  run_test.py           full application flow, headless
  run_demo_test.py      demo-mode checks
  paramiko.py           simulated AR730 speaking VRP
  tkinter/              headless substitute implementing real widget behaviour
  make_preview.py       generates an HTML preview of the interface
run.sh / run.bat        launchers
build_windows.bat       produces a standalone .exe via PyInstaller
```

The application is deliberately a **single file with no framework dependency** beyond
`paramiko`. It is meant to be readable end to end by whoever inherits it.

## Building a Windows executable

```bash
pip install paramiko pyinstaller
pyinstaller --onefile --windowed --name AR730Manager ar730_manager.py
```

Or double-click `build_windows.bat`. The result is `dist/AR730Manager.exe`, a single portable
file that needs no Python installation.

> Some antivirus products flag PyInstaller binaries because they are self-extracting. Add an
> exception, or run the tool as a Python script.

## Compatibility

| | |
|---|---|
| **Tested on** | Huawei NetEngine AR730 (VRP) |
| **Likely compatible** | Other Huawei AR-series routers using the same `aaa` / `local-user` / `mac-access-profile` model |
| **Python** | 3.9+ |
| **OS** | Windows, macOS, Linux |
| **Dependencies** | `paramiko` (runtime only — demo mode and the tests need nothing) |

Running it against another AR-series model? Please
[open an issue](https://github.com/AFZ92/ar730-access-manager/issues) and tell us what
worked — compatibility reports are genuinely useful.

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for how to set up, what the
test harness expects, and the conventions the codebase follows.

Good first contributions:

- Compatibility reports from other Huawei AR models
- Additional interface languages
- Bulk import of devices from CSV
- Packaging (Homebrew formula, `.deb`, MSI installer)

## License

Licensed under the [Apache License 2.0](LICENSE).

---

<div align="center">

**Powered by AFZ Systems**

<sub>Keywords: Huawei AR730 · NetEngine · VRP · MAC authentication · 802.1X · captive portal ·
network access control · NAC · MAC whitelist · router management GUI · Python · Tkinter ·
SSH automation · RTL Arabic interface</sub>

</div>
