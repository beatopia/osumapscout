# osumapscout

`osumapscout` is a planned osu!standard map recommendation web application. It aims to help a player discover maps they may enjoy by learning from their profile, top plays, map attributes, mod usage, and eventually the preferences of similar players.

The project is motivated by two goals: building a useful recommendation experience and developing a backend system whose important decisions remain understandable to its developer.

## Current status

The repository contains a minimal FastAPI backend with a `GET /health` endpoint and an osu! API client-credentials authentication boundary. User-profile fetching, top-play fetching, frontend, database, and recommendation functionality have not been implemented. Work is complete through T0003; T0004, fetching a basic osu! user profile, is expected next.

## Run the backend locally

Python 3.11 or newer is required. From the repository root, create a virtual environment and install the project dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install .
```

Start the development server:

```powershell
.\.venv\Scripts\python -m uvicorn backend.app.main:app --reload
```

The health endpoint is available at <http://127.0.0.1:8000/health>, and FastAPI's generated API documentation is available at <http://127.0.0.1:8000/docs>.

## Configure osu! API authentication

Register an OAuth application in your osu! account settings to obtain a client ID and client secret. The backend reads these credentials from operating-system environment variables; it does not load `.env` files automatically.

For the current PowerShell session, set:

```powershell
$env:OSU_CLIENT_ID = "your_client_id"
$env:OSU_CLIENT_SECRET = "your_client_secret"
```

`.env.example` lists the required names for reference. Never place real credentials in tracked files.

Verify token acquisition with:

```powershell
.\.venv\Scripts\python -m backend.app.osu.verify
```

The command reports only success or a developer-facing error; it never prints the access token. This authenticates the backend application for public API access and does not log an osu! user into `osumapscout`.

## Planned direction

The tentative stack is:

- Python and FastAPI for the backend
- React, TypeScript, and Vite for the frontend
- PostgreSQL for persistence, introduced after the first API-to-UI flow works

The intended architecture is a conventional monolithic web application: a React client calls a FastAPI REST API, application services hold business logic, and PostgreSQL provides persistence. Future osu! API access should be isolated behind a dedicated client or service boundary.

Development is intentionally incremental. Each ticket should add one understandable capability, and implementation findings may change later plans.

## Documentation

- [Full design document](docs/Full_Design_Document.md) — tentative long-term direction
- [MVP technical design](docs/MVP_Technical_Design.md) — nearer-term vertical build sequence
- [Ticket tracker](docs/Tickets.md) — current and planned tickets
- [Repository current state](docs/Repo_Current_State.md) — what exists now
- [Manual verification guide](docs/Manual_Verification_Guide.md) — how ticket results should be checked
- [Contributor and Codex rules](AGENTS.md) — repository-level implementation constraints
