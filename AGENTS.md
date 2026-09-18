# cme-oi — agent entry point

Read [`SKILL.md`](SKILL.md) and follow it. Everything that matters (product detection, the ask-then-run flow, the data traps) lives there.

Fast path:

```bash
python3 -m pip install curl_cffi
python3 scripts/report.py gold --period 1w      # or silver | oil | all
```

Rules that are easy to get wrong:

- No API keys anywhere. If a fetch fails, it is the transport, not authentication.
- CME requires `curl_cffi` with `impersonate="chrome"`. Plain HTTP clients get 403.
- The script owns presentation. Show its `--format md` output as-is; do not rebuild the tables.
- Ask for product and period when the user didn't state them (offer choices, don't guess).
- COT is weekly and covers through Tuesday; publication is Friday 15:30 ET (Saturday 04:30 JST). A missing latest week is normal, not an error.

Requirements and install: [`README.md`](README.md).
