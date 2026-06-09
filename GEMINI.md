# GEMINI.md

This file establishes durable context for Google AI agents operating within this repository.

## Current Architecture
- This is a Docs Shell.
- The actual ETL execution happens in a private, un-committed repository.
- We surface the `ThreadPoolExecutor` and SQLite methodology via sanitized excerpts in `examples/sanitized-code-excerpts/`.

## Agent Instructions
If asked to update the code, you must:
1. Verify you are modifying the sanitized excerpts, not live connected scripts.
2. Maintain the `Docs Shell` facade.
3. Add any major architectural shifts (e.g. migrating from SQLite to Postgres) to the `README.md` diagrams.
