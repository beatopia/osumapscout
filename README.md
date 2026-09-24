# osumapscout

`osumapscout` is a planned osu!standard map recommendation web application. It aims to help a player discover maps they may enjoy by learning from their profile, top plays, map attributes, mod usage, and eventually the preferences of similar players.

The project is motivated by two goals: building a useful recommendation experience and developing a backend system whose important decisions remain understandable to its developer.

## Current status

The repository contains a FastAPI backend with normalized top-play and persisted-player analysis endpoints plus a React, TypeScript, and Vite frontend. The frontend has separate actions for live top-play search and displaying persisted descriptive analysis. PostgreSQL stores explicitly persisted current top-play state, from which statistics are calculated on demand. Non-public backend experiments can discover candidates, compare candidate-map orderings and preference evidence, and evaluate known-positive recovery with deterministic held-out target plays. No recommendations are generated. Work is complete through T0029.

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

## Configure PostgreSQL for development

The backend uses PostgreSQL through synchronous SQLAlchemy and the Psycopg 3 driver. Install and run PostgreSQL locally, create an `osumapscout` development database, and use a local database user that can connect to it. PostgreSQL installation and user administration are external to this repository; Docker is not required.

Set the connection URL in the current PowerShell session, replacing the example credentials with your local values:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://USER:PASSWORD@localhost:5432/osumapscout"
```

The backend reads `DATABASE_URL` from the operating-system environment and does not load `.env` automatically. Verify the complete Python-to-PostgreSQL connection with:

```powershell
.\.venv\Scripts\python -m backend.app.database.verify
```

The command executes `SELECT 1` and creates no tables. Database setup does not affect `/health`, and the current osu! endpoints do not read from or write to PostgreSQL.

Apply the application schema explicitly after configuring `DATABASE_URL`:

```powershell
.\.venv\Scripts\python -m alembic upgrade head
```

For development verification, remove all application tables created by the migration with:

```powershell
.\.venv\Scripts\python -m alembic downgrade base
```

Run `upgrade head` again afterward to restore the schema. FastAPI never runs migrations or creates tables automatically.

With `OSU_CLIENT_ID`, `OSU_CLIENT_SECRET`, and `DATABASE_URL` configured, explicitly fetch and persist one user's profile and complete available top-play set with:

```powershell
.\.venv\Scripts\python -m backend.app.database.persist_user YOUR_USERNAME
```

The command requests up to 100 plays and transactionally replaces only that user's current persisted top plays. It updates shared beatmap metadata without duplicating beatmaps. Normal GET requests still fetch live osu! data and do not write to PostgreSQL.

After a user has been persisted, calculate their current descriptive statistics from PostgreSQL with:

```powershell
.\.venv\Scripts\python -m backend.app.analysis.player_stats YOUR_USERNAME
```

This command does not contact osu!, refresh data, or modify the database. It reports null-aware averages and deterministic exact-combination and individual-mod counts. Accuracy remains a `0`–`1` ratio in application results and is formatted as a percentage only by the command.

With FastAPI running, request the same persisted statistics as JSON at:

```text
GET http://127.0.0.1:8000/api/users/YOUR_USERNAME/analysis
```

The username must already have been persisted. This read-only endpoint requires database configuration but no osu! credentials, and requesting it does not fetch or refresh upstream data. API accuracy remains on the `0`–`1` scale.

Discover up to 100 candidate user identities for a persisted target with:

```powershell
.\.venv\Scripts\python -m backend.app.candidates.verify YOUR_USERNAME --limit 20
```

Persisted users are returned first in ascending numeric user-ID order. If they do not fill the requested capacity, the command follows at most three osu!standard performance-ranking responses. It excludes the target, deduplicates candidates by numeric user ID, shows `local` and `ranking` provenance, and reports the ranking request count. Ranking candidates remain ephemeral: this command does not fetch their top plays, persist them, calculate similarity, or recommend maps. A request satisfied entirely by local users does not require osu! credentials.

Fetch ephemeral top-play evidence for a small prefix of that candidate pool with:

```powershell
.\.venv\Scripts\python -m backend.app.candidates.verify_hydration YOUR_USERNAME --candidate-limit 10 --hydrate-limit 3 --top-plays 10
```

Hydration preserves discovery order and provenance, uses numeric user IDs directly, and performs one sequential best-score request per hydrated candidate. It accepts candidate-pool limits from 1 to 100, hydration limits from 1 to 10, and top-play depths from 1 to 100. Local candidates are fetched live through the same osu! API path as ranking candidates so evidence has one consistent source. Results remain ephemeral: no candidate profiles or plays are persisted, no public HTTP endpoint exists, and no similarity or recommendation is calculated.

Run the first ephemeral top-play overlap experiment with:

```powershell
.\.venv\Scripts\python -m backend.app.similarity.verify YOUR_USERNAME --candidate-limit 20 --hydrate-limit 5 --top-plays 100
```

The command reads the target's persisted plays, reuses bounded candidate hydration, and reports unique shared beatmap count, Jaccard similarity, and target coverage. Results are ordered by shared count, Jaccard, target coverage, and numeric user ID. This is an inspectable experiment rather than a final quality judgment: it adds no weights, thresholds, persistence, public endpoint, or map recommendations.

Experiment with a separate candidate source based on selected target-map leaderboards:

```powershell
.\.venv\Scripts\python -m backend.app.candidates.verify_target_maps YOUR_USERNAME --seed-count 5 --candidate-limit 30
```

The command deterministically spreads up to ten seed maps across the target's persisted top-play positions, makes one osu!standard leaderboard request per selected seed, and records which seeds discovered each unique user. It processes every seed before sorting and truncating candidates. This does not replace the existing ranking source, hydrate candidates, calculate similarity, persist results, or expose a public endpoint.

Evaluate a bounded prefix of those target-map candidates with both raw and seed-excluded overlap:

```powershell
.\.venv\Scripts\python -m backend.app.similarity.verify_target_maps YOUR_USERNAME --seed-count 5 --candidate-limit 30 --hydrate-limit 10 --top-plays 100
```

This command reuses target-map acquisition, fetches candidate top plays sequentially by numeric user ID, and reuses the existing shared-count, Jaccard, and target-coverage calculations. Seed-excluded metrics remove only the selected discovery seed maps from both users before comparison, exposing overlap beyond the acquisition evidence. Results and candidate plays remain ephemeral; no recommendation, persistence, endpoint, or frontend behavior is added.

Compare recurring target-map candidates with a deterministic, seed-stratified sample of one-hit candidates:

```powershell
.\.venv\Scripts\python -m backend.app.similarity.verify_one_hit_baseline YOUR_USERNAME --seed-count 5 --recurring-limit 20 --one-hit-limit 15 --top-plays 100
```

This developer experiment runs full target-map acquisition once, samples its complete pre-truncation candidate pool, hydrates both bounded groups sequentially by numeric user ID, and reports their raw and seed-excluded overlap separately. It also reports full-pool availability and one-hit availability/sample counts for every selected seed. The summaries contain counts, thresholds, totals, means, medians, and maxima only; they do not combine the evidence into a score or make a quality verdict. The result remains ephemeral and does not recommend maps. Unlike the bounded T0021 display command, this baseline intentionally has no `--candidate-limit` option because display truncation must not bias its sampling population.

Run the budgeted similar-player ranking experiment with:

```powershell
.\.venv\Scripts\python -m backend.app.similarity.verify_ranked_candidates YOUR_USERNAME --seed-count 5 --hydration-budget 25 --top-plays 100
```

This command spends its bounded hydration budget on recurring candidates first, then fills remaining capacity with the existing seed-stratified one-hit sampler. After hydration it ranks every evaluated user only by seed-excluded shared count, Jaccard, target coverage, and numeric user ID. Seed recurrence remains visible acquisition provenance but contributes no similarity points. Results remain ephemeral and are not map recommendations.

Extract an inspectable candidate-map pool from a bounded prefix of those ranked players with:

```powershell
.\.venv\Scripts\python -m backend.app.recommendation.verify_candidate_maps YOUR_USERNAME --seed-count 5 --hydration-budget 25 --top-plays 100 --similar-player-limit 10 --show-maps 30
```

The extraction reuses T0025's already-hydrated plays, strictly excludes the target's own top-play maps, deduplicates by beatmap ID, and reports distinct supporting-player evidence. It performs no additional osu! requests and does not score or label maps as recommendations.

Compare the T0026 support-only candidate-map order with an evidence-aware order using:

```powershell
.\.venv\Scripts\python -m backend.app.recommendation.verify_candidate_map_ranking YOUR_USERNAME --seed-count 5 --hydration-budget 25 --top-plays 100 --similar-player-limit 10 --show-maps 30
```

This experiment builds the candidate-map pool once and applies a lexicographic ordering by support count, total supporting-player independent overlap, mean independent overlap, best supporting-player rank, and beatmap ID. It reports old and new ranks with movement diagnostics, uses no weighted score or map attributes, and makes no additional requests.

Inspect descriptive target-preference evidence without changing the T0027 order:

```powershell
.\.venv\Scripts\python -m backend.app.recommendation.verify_preference_evidence YOUR_USERNAME --seed-count 5 --hydration-budget 25 --top-plays 100 --similar-player-limit 10 --show-maps 30
```

This experiment calculates persisted target star-rating, AR, BPM, and mod distributions, then annotates the unchanged candidate-map order with median deltas, inclusive-IQR membership, and supporting mod evidence. Missing metadata stays explicit, no attribute becomes a score or filter, and no additional osu! requests are made.

Run the offline held-out recovery experiment with:

```powershell
.\.venv\Scripts\python -m backend.app.recommendation.verify_holdout_recovery YOUR_USERNAME --top-plays 100 --holdout-count 10 --seed-count 5 --hydration-budget 25 --candidate-top-plays 100 --similar-player-limit 10
```

This command deterministically holds out an approximately even spread of persisted target plays, runs every target-dependent pipeline stage from training evidence only, and compares support-only with evidence-aware recovery. Persistence is not modified, and recovery evaluation adds no requests.

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

The shared username field provides two independent actions:

- **Search live top plays** calls the existing live osu! API-backed flow.
- **View persisted analysis** reads previously persisted statistics from PostgreSQL.

The analysis action does not fetch, persist, or refresh osu! data. Persist the username explicitly with the backend command before requesting its analysis.

## Planned direction

The tentative stack is:

- Python and FastAPI for the backend
- React, TypeScript, and Vite for the frontend
- PostgreSQL for persistence; the initial schema, migration, and explicit current-state ingestion workflow exist

The intended architecture is a conventional monolithic web application: a React client calls a FastAPI REST API, application services hold business logic, and PostgreSQL provides persistence. Future osu! API access should be isolated behind a dedicated client or service boundary.

Development is intentionally incremental. Each ticket should add one understandable capability, and implementation findings may change later plans.

## Documentation

- [Full design document](docs/Full_Design_Document.md) — tentative long-term direction
- [MVP technical design](docs/MVP_Technical_Design.md) — nearer-term vertical build sequence
- [Ticket tracker](docs/Tickets.md) — current and planned tickets
- [Repository current state](docs/Repo_Current_State.md) — what exists now
- [Manual verification guide](docs/Manual_Verification_Guide.md) — how ticket results should be checked
- [Contributor and Codex rules](AGENTS.md) — repository-level implementation constraints
