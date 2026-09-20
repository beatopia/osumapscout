# Full Design Document

## Status and scope

This document describes the tentative long-term direction for `osumapscout`. It is not a description of implemented functionality, and details should evolve in response to real API data and implementation findings.

## Problem and motivation

osu! players can have difficulty finding beatmaps that match their established tastes while still offering something new. `osumapscout` aims to make discovery more personal by using a player's actual osu!standard play history and, later, patterns shared with other players.

The project is also a learning-oriented backend engineering effort. Its architecture should stay small, explicit, and explainable so the developer can understand every important part of the system.

## Intended user experience

An eventual user should be able to identify an osu! account, see a useful summary of its top plays and preferences, and receive map suggestions. Recommendations should omit maps already represented in the user's own top plays and should support practical filters such as mods, BPM, approach rate, and star rating.

The exact interaction design remains unresolved and should be informed by the initial username lookup and top-play display.

## Major eventual capabilities

- Look up an osu!standard user and retrieve their profile and top plays.
- Normalize relevant osu! API data for use by the application.
- Analyze basic patterns such as mod usage and beatmap attributes.
- Persist selected user, score, and beatmap information when persistence is justified.
- Find players whose top plays overlap or exhibit useful similarity.
- Generate map recommendations from those relationships.
- Exclude already-known top-play maps and apply useful map filters.

These are planned capabilities, not current features.

## High-level architecture

The tentative architecture is a conventional monolithic web application:

```text
React frontend
      |
FastAPI REST API
      |
Service / application logic
      |
PostgreSQL
```

The monolith should remain the default unless observed requirements provide a concrete reason to change it. Boundaries within the application should clarify responsibilities without creating premature distributed infrastructure.

## Backend responsibilities

The planned FastAPI backend will handle HTTP requests, validate inputs, coordinate application services, normalize external data, and expose stable responses to the frontend. Route handlers should remain thin enough that API transport concerns do not absorb business logic.

Exact endpoints, module layout, caching behavior, and error contracts are intentionally not settled here.

## Frontend responsibilities

The planned React and TypeScript frontend will provide username lookup, loading and error feedback, top-play presentation, player analysis, and later recommendation controls. It should depend on the application's normalized API rather than osu! API response shapes directly.

Detailed component architecture and visual design remain tentative.

## Persistence responsibilities

PostgreSQL is the planned database once the initial live API-to-UI path is understood. Persistence may eventually retain users, beatmaps, scores, fetch metadata, and derived analysis needed by the product. The data model should be designed from observed osu! API payloads and actual queries; no detailed schema is established yet.

## External osu! API boundary

osu! API v2 access should eventually live behind a dedicated client or service boundary. That boundary should own authentication, request construction, external response handling, and translation of external failures. Route handlers and frontend code should not make scattered direct osu! API calls.

Credential handling, rate-limit behavior, retries, and caching will be specified when tickets encounter those needs.

## Recommendation-system direction

Candidate approaches include shared top plays, Jaccard similarity, cosine similarity, and weighted collaborative filtering. These are possibilities rather than selected algorithms. The project should first inspect real user, score, mod, and beatmap data; then it can define similarity, weighting, evaluation, and cold-start behavior with evidence.

## Possible future infrastructure

pytest, Docker, GitHub Actions, Redis, AWS, OAuth 2.0, and other infrastructure may become useful. None is assumed to be necessary now. Each should be introduced only by a ticket with a concrete requirement and an explainable benefit.

## Non-goals and overengineering warnings

- Do not split the application into microservices without demonstrated need.
- Do not create speculative abstractions, deployment systems, caches, or background workers.
- Do not design a complete database schema before inspecting actual data and access patterns.
- Do not commit to a recommendation algorithm before obtaining data suitable for evaluation.
- Do not hide understandable domain behavior behind unnecessary frameworks or dependencies.
- Do not optimize for production scale before a working, measurable product flow exists.

## Major unresolved questions

- Which osu! API fields are stable and useful for player analysis?
- How much top-play history is available and sufficient for meaningful results?
- Which normalized response shapes best serve the frontend?
- What data should be persisted, refreshed, or treated as transient?
- How should users with sparse or unusual play histories be handled?
- Which similarity signal produces recommendations that users consider relevant?
- What recommendation evaluation method is practical for the project?
- Which filters belong in the first recommendation experience?
