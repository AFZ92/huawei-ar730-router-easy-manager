## What this changes

<!-- One or two sentences. -->

## Why

<!-- The problem it solves. Link an issue if there is one. -->

## Checklist

- [ ] `python harness/run_test.py` passes every check
- [ ] `python harness/run_demo_test.py` passes every check
- [ ] New user-visible strings added to **both** `TXT` dictionaries (English and Arabic)
- [ ] Layout uses the `_side()` / `_anchor()` / `_pad()` helpers rather than hardcoded sides
- [ ] Any new router write reads the configuration back to verify it
- [ ] No real MACs, hostnames, serials or IP ranges in code, tests or comments
