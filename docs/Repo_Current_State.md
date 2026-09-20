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
- The client can reuse username lookup to retrieve up to 100 best osu!standard scores.
- Top plays retain a small typed set of score, mod, beatmap, beatmapset, and directly available difficulty fields.
- Top-play fetching can be checked with the non-public verification command documented in `README.md`.
- `GET /api/users/{username}/top-plays` exposes normalized top-play data with an optional limit from 1 through 100.
- The public response contains only explicitly supported application fields and maps expected upstream failures to HTTP responses.
- A minimal React, TypeScript, and Vite frontend skeleton exists under `frontend/` and can run locally.
- The frontend currently renders a static project introduction and does not communicate with the backend.
- No username search or real osu! data display exists in the frontend yet.
- No database integration or database configuration exists yet.
- No player-analysis system exists yet.
- No recommendation or similar-player logic exists yet.

## Ticket position

- Completed through: T0007 — React/Vite frontend skeleton
- Expected next ticket: T0008 — Username search flow

Future tickets must update this document when the repository's implemented state changes.
