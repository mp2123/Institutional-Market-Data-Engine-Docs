# AGENTS.md

## Mission
This repository is a Public Documentation Shell (`-Docs`) for the Institutional Market Data Engine. 

## Boundaries
- **DO NOT** commit real `.env` files, Schwab API keys, or OAuth tokens here.
- **DO NOT** commit the raw `market_data.db` file.
- Keep all raw code inside `examples/sanitized-code-excerpts/`.
- Ensure all repository documentation focuses on business logic, quantitative risk architecture, and data engineering patterns.

## Work Handoff
When resuming work on this repository:
1. Review `README.md` for the current public boundaries.
2. Review the sanitized code in `examples/sanitized-code-excerpts/` to understand the Python/SQLite architecture.
3. If modifying code, ensure you do not accidentally introduce hardcoded absolute paths or credentials before pushing.
