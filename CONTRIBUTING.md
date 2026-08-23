# Contributing

Thanks for considering a contribution. This project is small, single-purpose, and meant to
stay readable by whoever inherits it — please keep that in mind when proposing changes.

## Getting set up

```bash
git clone https://github.com/AFZ92/huawei-ar730-router-easy-manager.git
cd huawei-ar730-router-easy-manager
pip install -r requirements.txt
python ar730_manager.py --demo
```

Demo mode needs no router, no network, and not even `paramiko`. Use it for everything except
changes that specifically touch SSH transport.

## Run the tests before you open a PR

```bash
python harness/run_test.py        # full application flow
python harness/run_demo_test.py   # demo mode
```

Both must report every check passing. They need no display and no hardware.

## About the harness

`harness/` contains a headless substitute for `tkinter` and a simulated AR730 that speaks VRP.
The application is built for real and its buttons are pressed in order.

The substitute implements **real widget behaviour**, not stubs that always succeed. Traces
fire, bindings are recorded, `pack` order is tracked, `Treeview` refuses to delete a row that
does not exist. That is deliberate: a test double that cannot fail proves nothing.

**If you add a feature, extend the harness rather than skipping the test.** If a widget method
you need is missing, implement it faithfully. Several bugs in this project's history were
caught only because the harness modelled Tk closely enough to reproduce them.

## Conventions

- **One file.** The application lives in `ar730_manager.py`. Resist the urge to split it into
  a package; it is meant to be read end to end.
- **No new runtime dependencies** without discussion. `paramiko` is the only one.
- **Comments explain *why*, not *what*.** Most comments in this codebase record a VRP
  behaviour or a Tk constraint that is not obvious from the code. Match that.
- **Every user-visible string goes in both `TXT` dictionaries** — English and Arabic.
- **Respect layout direction.** Use the `_side()`, `_anchor()`, `_pad()` and `_justify()`
  helpers instead of hardcoding `"left"` / `"w"`. RTL is not an afterthought here.
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
