# MVP Technical Design

## Purpose

The MVP should grow through small vertical steps that expose real constraints early. The initial FastAPI application and health endpoint now exist; the remaining steps below describe planned work.

## Incremental build strategy

1. Create a minimal FastAPI backend that can start and expose a simple verification route.
2. Add osu! API client-credentials authentication behind a dedicated integration boundary.
3. Fetch a user by username or supported identifier and observe the real profile response.
4. Fetch that user's osu!standard top plays and examine the available score, mod, and beatmap data.
5. Normalize backend responses so the frontend does not depend directly on external API payloads.
6. Create a React, TypeScript, and Vite frontend.
7. Build a username lookup flow against the normalized backend API.
8. Display the returned top plays with appropriate loading, empty, and failure states.
9. Only after that end-to-end flow works, introduce PostgreSQL development setup and design persistence around observed data and access needs.
10. After persistence behavior is understood, calculate basic player statistics and expose them to an analysis UI.

Each step should remain independently understandable and manually verifiable. Later tickets may revise this ordering when implementation findings justify it.

## Backend MVP responsibilities

The backend is expected to own osu! API communication, input validation, error translation, and normalized application responses. HTTP routes should delegate integration and application logic rather than becoming large business-logic modules. Precise endpoint contracts will be established by their implementation tickets, not speculated here.

## Frontend MVP responsibilities

The frontend is expected to accept a username, call the application backend, and clearly render profile or top-play data along with meaningful loading and failure states. Strict TypeScript should be used once the frontend exists.

## Persistence timing

PostgreSQL should not block learning from the first live vertical flow. It should be added after user lookup and top-play display work, so the schema is shaped by observed API data and concrete queries. Detailed tables and relationships are deliberately deferred.

## Deferred recommendation design

Similar-player discovery and map recommendations are outside the initial MVP sequence above. They will be designed in more detail only after real osu! API data has been examined and basic acquisition, normalization, persistence, and analysis behavior is understood.

## MVP boundaries

This design does not yet specify detailed HTTP endpoints, a database schema, authentication for application users, recommendation algorithms, deployment architecture, caching, background processing, or production infrastructure.
