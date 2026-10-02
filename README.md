# osu! Map Scout

A web app that recommends osu!standard maps based on a player's top plays and the maps played by similar users.

## How It Works

Given an osu! username, the app:

1. Fetches the player's profile and top plays.
2. Analyzes things like mods, star rating, AR, and BPM.
3. Finds similar players using overlap between top plays.
4. Looks at maps those players perform well on.
5. Filters out maps already in the target player's top plays.
6. Ranks the remaining maps using collaborative and playstyle evidence.

## Notes

- osu!standard only
- Uses the official osu! API v2
- API credentials are loaded from environment variables and should never be committed

## Local setup

Requirements: Python 3.11+, Node.js, and PostgreSQL.

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -e .
Copy-Item .env.example .env
# Fill in the local values in .env, then load them into your shell.
.\.venv\Scripts\alembic upgrade head
.\.venv\Scripts\uvicorn backend.app.main:app --reload
```

In another terminal:

```powershell
cd frontend
npm ci
npm run dev
```

The Vite development server proxies `/api` to the local backend. For a separately hosted frontend, set `VITE_API_BASE_URL` at build time and list its exact origin in the backend's comma-separated `CORS_ORIGINS` value.

## Deployment

The intended deployment is a static frontend, one FastAPI process, and PostgreSQL. Run `alembic upgrade head` before starting the API with a production ASGI server. The backend requires `DATABASE_URL`, `OSU_CLIENT_ID`, and `OSU_CLIENT_SECRET`; `CORS_ORIGINS` is required when the frontend is hosted on another origin.

`/health` checks the process, while `/ready` also checks database connectivity. Static hosting must rewrite `/player/*` paths to `index.html` so shared player URLs survive refreshes.
