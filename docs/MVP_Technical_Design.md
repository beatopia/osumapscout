# MVP Technical Design

## Purpose

The MVP grows through small vertical steps that expose real constraints early. The live backend-to-frontend top-play flow now exists through T0009, and T0010 documents the evidence-based persistence requirements before database implementation begins.

## Incremental build strategy

1. Create a minimal FastAPI backend that can start and expose a simple verification route.
2. Add osu! API client-credentials authentication behind a dedicated integration boundary.
3. Fetch a user by username or supported identifier and observe the real profile response.
4. Fetch that user's osu!standard top plays and examine the available score, mod, and beatmap data.
5. Normalize backend responses so the frontend does not depend directly on external API payloads.
6. Create a React, TypeScript, and Vite frontend.
7. Build a username lookup flow against the normalized backend API.
8. Display the returned top plays with appropriate loading, empty, and failure states.
9. Document recommendation data requirements and the minimum persistence design from the working vertical slice.
10. Introduce PostgreSQL development setup, then implement the minimal user, beatmap, and current top-play persistence model in separate tickets.
11. After persistence behavior is understood, calculate basic player statistics and expose them through an analysis endpoint and UI follow-up.

Each step should remain independently understandable and manually verifiable. Later tickets may revise this ordering when implementation findings justify it.

## Backend MVP responsibilities

The backend is expected to own osu! API communication, input validation, error translation, and normalized application responses. HTTP routes should delegate integration and application logic rather than becoming large business-logic modules. Precise endpoint contracts will be established by their implementation tickets, not speculated here.

## Frontend MVP responsibilities

The frontend is expected to accept a username, call the application backend, and clearly render profile or top-play data along with meaningful loading and failure states. Strict TypeScript should be used once the frontend exists.

## Persistence timing

PostgreSQL did not block learning from the first live vertical flow. The next implementation phase may now introduce it, guided by `Recommendation_Data_Design.md`. Database setup, schema/migrations, and ingestion remain separate incremental tickets.

## Deferred recommendation design

Similar-player discovery and map recommendation implementation remain deferred. T0010 identifies their data needs, but candidate-user discovery is still an unresolved research problem and no similarity formula has been selected.

## MVP boundaries

This design does not specify future HTTP endpoints, a database schema, authentication for application users, recommendation algorithms, deployment architecture, caching, background processing, or production infrastructure.
