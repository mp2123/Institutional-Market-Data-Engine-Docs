# AGENTS.md

## Mission
This repository is a Public Documentation Shell (`-Docs`) for the Institutional Market Data Engine. 

## Boundaries
- **DO NOT** commit real `.env` files, Schwab API keys, or OAuth tokens here.
- **DO NOT** commit the raw `market_data.db` file.
- Keep excerpts under `examples/sanitized-code-excerpts/` sanitized: placeholder credentials only, no local absolute paths, no token files, no live account data.
- Ensure all repository documentation focuses on market-data ingestion architecture, analytics workflow, validation, and privacy boundaries.
- Keep public wording humble and evidence-backed. Do not describe this as a professional trading system, institutional platform, or production quant engine.

## Work Handoff
When resuming work on this repository:
1. Review `README.md` for the current public boundaries.
2. Review the sanitized code in `examples/sanitized-code-excerpts/` to understand the Python/SQLite architecture.
3. If modifying code, ensure you do not accidentally introduce hardcoded absolute paths or credentials before pushing.
4. Run a path-only secret scan before push, and rotate/revoke credentials outside the repo if any real value ever appears in public history.
