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
- The backend-to-frontend vertical slice works from username submission through normalized top-play rendering.
- A minimal React, TypeScript, and Vite frontend skeleton exists under `frontend/` and can run locally.
- The frontend has a username search form that calls the backend through a Vite development proxy.
- Loading, success, empty-input, and request-error states are implemented.
- Returned top plays are displayed in backend order with their rank, map identity, mods, PP, accuracy, and available score details.
- Directly available star rating, AR, and BPM values are displayed without additional enrichment requests.
- PostgreSQL is the development database, configured through the single `DATABASE_URL` environment variable.
- The backend has a lazy, synchronous SQLAlchemy 2.x engine and session-factory foundation using Psycopg 3.
- A non-public verification command can connect to PostgreSQL and execute `SELECT 1` without creating tables.
- FastAPI application import and `GET /health` remain independent of database configuration and connectivity.
- SQLAlchemy 2.x ORM models define `users`, `beatmaps`, and `user_top_plays` with explicit relationships and current-state constraints.
- Alembic is configured to read the same `DATABASE_URL`; its initial migration can create and remove the application schema explicitly.
- No schema is created or migrated automatically during FastAPI startup or requests.
- A non-public command can fetch a profile and up to 100 top plays, then transactionally persist the user's complete current state.
- User and beatmap rows are updated by stable osu! IDs, shared beatmaps are reused, and stale top-play relationships for only the refreshed user are removed.
- Existing GET requests still fetch live osu! data and do not automatically read from or write to PostgreSQL.
- A database-only analysis function and non-public command calculate current top-play counts, null-aware PP/accuracy/map-attribute averages, exact mod combinations, and individual mod usage.
- Player statistics are computed on demand from persisted rows; they are not persisted and do not contact osu!.
- `GET /api/users/{username}/analysis` exposes the persisted user's statistics through an explicit JSON response model.
- The analysis endpoint reads PostgreSQL only; it does not call osu!, refresh the user, or write persistence data.
- The frontend can display persisted summary averages, exact mod combinations, and individual mod usage through a dedicated analysis action.
- Live top-play search and persisted analysis share the username input but remain separate requests with separate results and errors.
- No recommendation or similar-player logic exists yet.
- T0010 documents current data, the conceptual minimum persistence model, recommendation data needs, and unresolved similar-player discovery questions in `docs/Recommendation_Data_Design.md`.
- T0017 documents official candidate-user sources, their costs and biases, the missing reverse-top-play lookup, and a bounded hybrid recommendation in `docs/Similar_Player_Discovery_Research.md`.
- No candidate-user discovery, similarity metric, crawler, dataset import, or recommendation behavior was implemented by T0017.

## Ticket position

- Completed through: T0017 — Similar-player discovery feasibility research
- Expected next ticket: T0018 — Bounded candidate-user discovery prototype

Future tickets must update this document when the repository's implemented state changes.
