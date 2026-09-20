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
- A dedicated osu! API client boundary can request an application access token using the OAuth 2.0 client-credentials grant.
- osu! credentials are read from `OSU_CLIENT_ID` and `OSU_CLIENT_SECRET` environment variables.
- Token acquisition can be checked with the verification command documented in `README.md` without displaying the token.
- The osu! API client can fetch a basic osu!standard profile from a normal username.
- Profile lookup internally uses the current `@username` form and returns a small typed representation.
- Profile fetching can be checked with the non-public verification command documented in `README.md`.
- No osu! top-play fetching exists yet.
- No frontend application exists yet.
- No database integration or database configuration exists yet.
- No recommendation or similar-player logic exists yet.

## Ticket position

- Completed through: T0004 — Fetch basic osu! user profile
- Expected next ticket: T0005 — Fetch user top plays

Future tickets must update this document when the repository's implemented state changes.
