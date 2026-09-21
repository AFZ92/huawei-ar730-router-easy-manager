# Working on this project

A Qt desktop application (`ar730_qt.py`) with a router engine (`ar730_manager.py`) that manages
a production Huawei AR730 (VRP V300R024C00SPC100) over SSH.

## Before touching router commands

Read [`docs/router/README.md`](docs/router/README.md). It links:

- `terminal-behaviour.md`: prompts, reply endings, error formats, Y/N questions, and the `?` and
  paste pitfalls.
- `command-reference.md`: every command seen on the device, with its exact reply and status
  (✅ / ⛔ / ❓).
- `lessons-learned.md`: proven causes of past failures, and the rules we now follow.
- `captures/`: raw, sanitised terminal output. Copy replies from here into the simulators; never
  write them from memory.

For the captive portal, read [`docs/portal/README.md`](docs/portal/README.md).

## Rules with the real router

- The user runs router commands and pastes the output. Claude may only `curl` the portal at
  `10.0.255.1:8080`, read-only.
- If a command's reply is not in `command-reference.md` (or marked ❓), ask for it before coding
  against it. Then record it in the reference, `captures/` and both simulators.
- Help lines: `?` only on incomplete stems, one per step, and have the user clear the line with
  `Ctrl+U`. A complete command followed by `?` gets **executed** when the next line is pasted.
- Give command blocks that start by entering their view, and state the prompt the user should see.
  Ask the user to press Enter before pasting, because the first character may be lost.
- Give the rollback command before every change. **No `save` until the change is tested.**
- Mask passwords everywhere: logs, docs, captures, chat summaries.

## Code and tests

- Tests: `QT_QPA_PLATFORM=offscreen .venv/bin/python harness/run_qt_test.py` must pass.
- The simulator is `_DemoDevice`/`_DemoMgmt`/`_DemoWan` in `ar730_manager.py`, used by Qt
  `--demo`. A behaviour belongs in it only once it is recorded in
  `docs/router/`.
- User-facing text exists in both Arabic and English (`TXT`). Update both.
- Add user-visible changes to `CHANGELOG.md` under `[Unreleased]`.
- Commit only when the user explicitly asks.
