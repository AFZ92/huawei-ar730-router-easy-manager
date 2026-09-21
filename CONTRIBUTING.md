# Contributing

Thanks for considering a contribution. This project is small, single-purpose, and meant to
stay readable by whoever inherits it — please keep that in mind when proposing changes.

## Getting set up

```bash
git clone https://github.com/AFZ92/huawei-ar730-router-easy-manager.git
cd huawei-ar730-router-easy-manager
pip install -r requirements.txt
python ar730_qt.py --demo
```

Demo mode needs no router, no network, and not even `paramiko`. Use it for everything except
changes that specifically touch SSH transport.

## Run the tests before you open a PR

```bash
QT_QPA_PLATFORM=offscreen python harness/run_qt_test.py
```

The test must report every check passing. It needs no display and no hardware.

## About the harness

`harness/run_qt_test.py` starts the Qt application offscreen against the simulated AR730 and
executes the supported flows. Extend it with each user-visible feature.

## Conventions

- **UI and engine.** `ar730_qt.py` owns the desktop UI; `ar730_manager.py` owns router protocol,
  validation and the simulator.
- **No new runtime dependencies** without discussion. The supported runtime is `PySide6` and
  `paramiko`.
- **Comments explain *why*, not *what*.** Most comments record a proven VRP behaviour.
- **Every user-visible string goes in both `TXT` dictionaries** — English and Arabic.
- **Respect layout direction.** Verify both Qt LTR and RTL layouts. RTL is not an afterthought.
- **Verify writes.** Any new router operation must read the configuration back and confirm the
  change actually took hold. Never infer success from the absence of an error.

## Never commit

- `ar730_settings.json`, `ar730_devices.json`, `ar730_session.log` — these hold live network
  data: the shared MAC password, device owner names, and full session transcripts.
- Real MAC addresses, hostnames, serial numbers, or IP ranges from a production network.

For examples and test fixtures, use the documentation MAC range reserved by
[RFC 7042](https://www.rfc-editor.org/rfc/rfc7042): `00-00-5E-00-53-00` through
`00-00-5E-00-53-FF`.

`.gitignore` covers the runtime files, but check `git status` before committing anyway.

## Reporting a bug

Include:

- What you did, what happened, what you expected
- The relevant section of the **Command Log** tab — with any real MACs, hostnames and IPs
  replaced
- Router model and VRP version
- OS and Python version

## Compatibility reports

If you run this against a Huawei AR model other than the AR730, please open an issue saying
what worked and what did not, even if everything worked. Those reports are one of the most
useful things you can contribute.
