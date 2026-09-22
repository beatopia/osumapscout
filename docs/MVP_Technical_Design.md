# MVP Technical Design

## Purpose

The MVP grows through small vertical steps that expose real constraints early. The live backend-to-frontend top-play flow exists through T0009, T0010 documents persistence requirements, T0011–T0013 establish PostgreSQL and explicit current-state ingestion, T0014–T0015 derive and expose basic statistics, and T0016 displays that persisted analysis in the frontend.

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
10. Introduce synchronous SQLAlchemy and Psycopg 3 configuration for a local PostgreSQL database, independently of HTTP application startup.
11. Implement the minimal user, beatmap, and current top-play schema with a versioned migration.
12. Add an explicit transactional workflow that fetches and replaces one user's complete current top-play state without changing GET behavior.
13. Calculate null-aware basic player statistics on demand from persisted current top plays.
14. Expose reusable statistics through a database-only player-analysis endpoint.
15. Present that API through an analysis UI that remains distinct from live top-play search.
16. Research documented candidate-user sources, API cost, sampling bias, cold start, and dataset constraints before implementing discovery.
17. Prototype a bounded candidate pool from persisted users plus a capped official performance-ranking sample, without fetching candidate top plays or calculating similarity.

Each step should remain independently understandable and manually verifiable. Later tickets may revise this ordering when implementation findings justify it.

## Backend MVP responsibilities

The backend is expected to own osu! API communication, input validation, error translation, and normalized application responses. HTTP routes should delegate integration and application logic rather than becoming large business-logic modules. Precise endpoint contracts will be established by their implementation tickets, not speculated here.

## Frontend MVP responsibilities

The frontend is expected to accept a username, call the application backend, and clearly render profile or top-play data along with meaningful loading and failure states. Strict TypeScript should be used once the frontend exists.

## Persistence timing

PostgreSQL did not block learning from the first live vertical flow. T0011 provides the connection foundation, T0012 adds typed ORM models and migrations, and T0013 transactionally replaces one user's complete current state. T0014 computes descriptive statistics from those rows, and T0015 exposes the same reusable result through a thin read-only HTTP route. Statistics are neither fetched from osu! nor persisted.

The frontend now keeps two explicit flows behind one username input: live top-play search reaches osu! through FastAPI, while persisted analysis reaches PostgreSQL through FastAPI. Neither action automatically triggers the other.

## Deferred recommendation design

T0017 resolved the first research direction but did not implement it. No documented reverse lookup maps a beatmap to all users who hold it in their best-score list. The next proposed step is a bounded local-plus-ranking candidate acquisition prototype; its ranking cursor assumptions must be verified in practice. Candidate top-play hydration, similarity formulas, and recommendations remain deferred.

## MVP boundaries

This design does not specify future HTTP endpoints beyond those already implemented, application-user authentication, recommendation algorithms, deployment architecture, caching, background processing, or production infrastructure. The implemented minimum persistence schema remains documented in `Recommendation_Data_Design.md` and its migration rather than expanded speculatively here.
