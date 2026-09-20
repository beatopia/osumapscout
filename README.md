# osumapscout

`osumapscout` is a planned osu!standard map recommendation web application. It aims to help a player discover maps they may enjoy by learning from their profile, top plays, map attributes, mod usage, and eventually the preferences of similar players.

The project is motivated by two goals: building a useful recommendation experience and developing a backend system whose important decisions remain understandable to its developer.

## Current status

The repository contains a FastAPI backend with a normalized top-play endpoint and a React, TypeScript, and Vite frontend. The frontend can search by osu! username and display returned top plays with basic score and map attributes. Database, persistence, analysis, and recommendation functionality have not been implemented. Work is complete through T0009; T0010, PostgreSQL development setup, is expected next.

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

Verify an osu!standard profile lookup with a normal username:

```powershell
.\.venv\Scripts\python -m backend.app.osu.verify_user peppy
```

The command prints only the normalized profile fields used by the application. It is a local verification tool, not a public FastAPI endpoint.

Fetch a concise top-play summary with:

```powershell
.\.venv\Scripts\python -m backend.app.osu.verify_top_plays peppy --limit 10
```

The limit must be from 1 to 100. This remains useful for inspecting the client directly; the application-facing HTTP endpoint is described below.

With the backend running and credentials configured, request normalized top plays at:

```text
GET http://127.0.0.1:8000/api/users/USERNAME/top-plays?limit=10
```

The endpoint defaults to 10 plays and accepts limits from 1 through 100. It returns the application's supported fields rather than the raw osu! API response.

## Run the frontend locally

From the repository root, install the frontend dependencies:

```powershell
cd frontend
npm install
```

Start the Vite development server in a second terminal while the FastAPI backend is running:

```powershell
npm.cmd run dev
```

Use the local URL printed by Vite. During development, Vite forwards relative `/api` requests to FastAPI at `http://127.0.0.1:8000`. To verify the production build, run `npm.cmd run build` from `frontend/`.

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
