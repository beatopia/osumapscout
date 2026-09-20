# osumapscout

`osumapscout` is a planned osu!standard map recommendation web application. It aims to help a player discover maps they may enjoy by learning from their profile, top plays, map attributes, mod usage, and eventually the preferences of similar players.

The project is motivated by two goals: building a useful recommendation experience and developing a backend system whose important decisions remain understandable to its developer.

## Current status

The repository currently contains only its documentation foundation. No backend, frontend, database, osu! API integration, or recommendation functionality has been implemented. T0001 is complete; T0002, the FastAPI application skeleton, is expected next.

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
