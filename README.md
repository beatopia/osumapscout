# osumapscout

`osumapscout` is a planned osu!standard map recommendation web application. It aims to help a player discover maps they may enjoy by learning from their profile, top plays, map attributes, mod usage, and eventually the preferences of similar players.

The project is motivated by two goals: building a useful recommendation experience and developing a backend system whose important decisions remain understandable to its developer.

## Current status

The repository contains a minimal FastAPI backend with a `GET /health` endpoint. No frontend, database, osu! API integration, or recommendation functionality has been implemented. Work is complete through T0002; T0003, osu! API authentication and client credentials, is expected next.

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
