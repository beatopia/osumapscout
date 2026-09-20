# Repository Current State

This file records what exists now, not what the project intends to build later.

## Current snapshot

- The repository documentation foundation exists.
- `README.md` describes the project and points to its core documents.
- `AGENTS.md` defines repository-level rules for future Codex work.
- Long-term design, MVP direction, ticket tracking, and manual verification guidance are documented under `docs/`.
- A minimal FastAPI backend exists in `backend/app/`.
- The backend can be started locally with the development command documented in `README.md`.
- `GET /health` returns `{"status": "ok"}` when the backend is running.
- No frontend application exists yet.
- No database integration or database configuration exists yet.
- No osu! API integration or authentication exists yet.
- No recommendation or similar-player logic exists yet.

## Ticket position

- Completed through: T0002 — FastAPI application skeleton
- Expected next ticket: T0003 — osu! API authentication/client credentials

Future tickets must update this document when the repository's implemented state changes.
