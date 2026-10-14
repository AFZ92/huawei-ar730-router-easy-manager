# Local AI/router bridge

`scripts/router_agent_bridge.py` keeps one interactive SSH shell open for a
local operator and an AI assistant. It is deliberately separate from the
desktop application: the application's rule that it never persists SSH
passwords remains unchanged.

## Prepare it once

1. Open the ignored local file `router_agent.local.json` and set `host`,
   `username`, and `password`. Do not share it, commit it, or paste it into a
   chat.
2. Restrict it to your account:

   ```bash
   chmod 600 router_agent.local.json
   ```

3. Start the bridge in a dedicated terminal and leave it running:

   ```bash
   .venv/bin/python scripts/router_agent_bridge.py serve
   ```

   It prints a small JSON readiness record. It opens exactly one SSH shell and
   runs `screen-length 0 temporary`, as the AR730 terminal requires.

## Safety boundary

- `allow_write` is `false` by default. Only `display`, `ping`, and `return`
  commands are accepted.
- To enable a requested, reviewed router change, set `allow_write` to `true`
  in the local file **before starting a new bridge session**. A caller must
  still mark that one request as a write; this prevents a read from becoming a
  configuration action by accident.
- The Unix socket has mode `0600` and is created in `/tmp` under the current
  user. No network listener is created.
- All forwarded commands and replies are appended to the ignored,
  mode-`0600` `router_agent_sessions.jsonl`, with clear-text password patterns
  redacted. Treat configuration output as sensitive and sanitise it before
  copying a useful result to `docs/router/captures/`.

## Stop it

From another terminal:

```bash
.venv/bin/python scripts/router_agent_bridge.py stop
```

The process closes its SSH shell and removes its local socket. It does not
issue `save` and never changes router configuration while stopping.
