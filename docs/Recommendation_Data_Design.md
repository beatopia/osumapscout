# Recommendation Data and Persistence Design

## Status and purpose

This document records the evidence and persistence direction established by T0010. T0012 implements the minimum relational schema, T0013 adds explicit current-state ingestion, and T0014 computes basic descriptive statistics on demand. Recommendation behavior does not exist yet.

The design is intentionally minimal. It should guide the next persistence tickets without locking the project into an untested recommendation formula or an unverified osu! API capability.

## Data currently available

### User profile

The existing osu! client can obtain this typed profile data:

| Field | Current type | Meaning |
| --- | --- | --- |
| `user_id` | integer | Stable osu! user identifier |
| `username` | string | Mutable display and lookup name |
| `country_code` | string | Profile display metadata |
| `avatar_url` | string | Profile display metadata |
| `global_rank` | integer or null | Volatile profile statistic |
| `performance_points` | number or null | Volatile profile statistic |

This profile is available inside the osu! client. The current public top-play endpoint returns the requested username but does not expose the full profile.

### Top plays

The backend and frontend intentionally support the following fields for each play:

| Field | Required now? | Notes |
| --- | --- | --- |
| `score_id` | No | External score identity when osu! supplies it |
| `beatmap_id` | Yes | Identifies a specific beatmap difficulty |
| `beatmapset_id` | No | Groups related difficulties |
| `artist` | No | Display metadata |
| `title` | No | Display metadata |
| `difficulty_name` | No | Difficulty/version display metadata |
| `performance_points` | No | PP awarded for this play |
| `accuracy` | No | Decimal proportion, not a percentage string |
| `grade` | No | Score grade/rank such as `S` |
| `mods` | Yes | Ordered acronyms; an empty collection means NM |
| `max_combo` | No | Maximum combo achieved in the play |
| `played_at` | No | Upstream play timestamp |
| `star_rating` | No | Beatmap difficulty value included with the score |
| `approach_rate` | No | Beatmap AR included with the score |
| `bpm` | No | Beatmap BPM included with the score |

Top-play position is currently implicit in the order of the returned list. It is not a field on `OsuTopPlay` or the HTTP play model. A persistence workflow that fetches a complete ordered list can enumerate that order into an explicit position.

## Data requirements by purpose

### User identity

The osu! numeric user ID is the stable external identifier and should anchor relationships. Username, country code, avatar URL, rank, and total PP are useful display or observation data, but they can change and must not serve as relationship keys.

### User play data

A persisted top-play relationship needs the user ID and beatmap ID, plus the score ID when available. Position, PP, accuracy, grade, mods, combo, play time, and fetch time preserve the evidence needed to compare players and explain why a map matters to them.

Position matters because a shared #1 play is potentially stronger evidence than a shared #99 play. It must come from the ordered response rather than being inferred from PP after storage.

### Beatmap identity

Beatmap ID identifies one difficulty and should be the stable external key. Beatmapset ID groups difficulties but does not identify a playable difficulty by itself. Artist, title, and difficulty name are display metadata and should not be used as identifiers.

### Beatmap attributes

| Attribute category | Current status | Initial assessment |
| --- | --- | --- |
| Star rating, AR, BPM | Present but nullable | Useful immediately when supplied |
| Map length | Not in the normalized contract | Likely useful for an early preference model; later enrichment needed |
| OD, CS, HP | Not in the normalized contract | Useful later; validate value before expanding the MVP |
| Hit-object counts and slider/object composition | Not in the normalized contract | Useful later for richer playstyle analysis |
| Creator/mapper | Not in the normalized contract | Useful later for display and preference signals |
| Ranked/status information | Not in the normalized contract | Likely needed before candidate eligibility rules become important |
| Mod-adjusted attributes | Not represented separately | Unresolved; raw and adjusted values must not be confused |

Missing attributes should remain null or absent. The application must not calculate or imply values that were not fetched. No extra beatmap request is part of the current implementation.

### Mod data

Mods must remain structurally usable as individual acronyms so NM, HD, HR, DT, HDHR, and future combinations can be distinguished. For an initial schema, storing the acronym collection on the play relationship is simpler and more faithful than introducing `Mod`, `PlayMod`, or aggregate-statistic tables. Empty means NM. Normalization can be reconsidered only if concrete queries or mod settings require it.

## Initial recommendation signals

These are candidate signals to test, not implemented or finalized algorithms:

- **Shared-map overlap:** two players have the same beatmap ID in their top plays.
- **Weighted overlap:** shared maps receive different importance based on top-play position, PP contribution, or later evidence such as recency. No formula is selected.
- **Mod preference similarity:** compare observed NM, HD, HR, DT, and combination usage without reducing combinations prematurely.
- **Map-attribute similarity:** compare available star rating, AR, and BPM; consider length only after enrichment exists.
- **Candidate discovery:** select maps present in similar players' top plays but absent from the target user's own top plays.
- **Explanation evidence:** retain which similar users, shared maps, mod patterns, and attribute ranges supported a candidate.

Explanation evidence should initially be produced from the same raw relationships used for ranking. A separate explanation table is not justified yet.

## Persist versus compute

### Persist initially

- Stable user identity and current display/profile fields needed by the product.
- Stable beatmap identity, beatmapset association, current display metadata, and attributes already acquired.
- Current user-to-top-play relationships, including explicit response position.
- Score evidence such as score ID, PP, accuracy, grade, mods, combo, and played time.
- Fetch timestamps that show when external observations were obtained.

These values are useful across requests, establish relational evidence, or would otherwise require repeated external calls.

### Compute on demand initially

- Shared-map counts and similarity scores.
- Mod distributions and preferred mod combinations.
- Average or range summaries for BPM, AR, star rating, and later attributes.
- Recommendation candidate scores and final rankings.
- Explanation text or explanation scores.
- Player classifications and preference vectors.

Derived values should remain reproducible from persisted observations while formulas are still changing. Persisting them now would create invalidation and versioning problems without demonstrated performance need.

## Current state versus historical snapshots

For the persistence MVP, store the **current known complete top-play set** for each user. A successful refresh of the intended top 100 should update the user's relationships and remove relationships no longer present. An arbitrary partial request must not be treated as a complete snapshot.

This is simpler than retaining every fetch and is sufficient for the first similarity experiments. Each record or refresh batch still needs `fetched_at`, so consumers know how old the observation is.

Historical snapshots are deliberately deferred. A later design can add a snapshot/fetch entity and associate observations with it if trend analysis, auditing, or recommendation reproducibility becomes a real requirement. The initial entities should not pretend to provide history.

## Candidate minimum relational model

This is conceptual and is not SQL or an ORM specification.

### User

- **Purpose:** identify an osu! player whose data has been fetched.
- **Likely primary identifier:** osu! numeric user ID.
- **Important fields:** username, country code, avatar URL, nullable global rank and total PP, and profile fetch time.
- **Relationships:** one user has many current top-play relationships.

### Beatmap

- **Purpose:** identify one playable difficulty and hold reusable map metadata.
- **Likely primary identifier:** beatmap ID.
- **Important fields:** nullable beatmapset ID, artist, title, difficulty name, star rating, AR, BPM, and beatmap data fetch time.
- **Relationships:** one beatmap may occur in many users' top plays.

### UserTopPlay

- **Purpose:** represent one user's current top-play evidence for one beatmap.
- **Likely identity:** user ID plus beatmap ID for the current-state MVP; score ID should also be retained when available.
- **Important fields:** explicit top-play position, nullable score ID, PP, accuracy, grade, mods, max combo, played time, and fetched time.
- **Relationships:** belongs to one user and one beatmap.

The implemented current-state schema uses user ID plus beatmap ID as the composite primary key. Score ID cannot be the key because it is nullable, and user ID plus position changes as rankings refresh. A separate unique constraint on user ID plus position ensures one current entry occupies each rank slot.

Do not create `Recommendation`, `SimilarUser`, `UserPreferenceVector`, `CachedAnalysis`, `ModStatistic`, or `RecommendationExplanation` tables initially.

## Freshness

osu! profiles, top plays, ranks, PP, and map metadata can change. Persistence therefore needs a fetch timestamp such as `fetched_at` for externally observed state. This supports stale-data decisions and makes results explainable without selecting a cache TTL now. Refresh frequency, expiration rules, retry policy, and caching remain future operational decisions.

## Additional API data requirements

No additional endpoint has been verified or implemented for these needs. They are classified requirements for later research.

| Data | Classification | Reason |
| --- | --- | --- |
| Map length | Likely needed for recommendation MVP | Duration may be a meaningful preference dimension |
| Ranked/status information | Likely needed for recommendation MVP | Candidate eligibility may depend on map status |
| OD, CS, HP | Useful later | Adds richer difficulty preference information |
| Object counts and slider composition | Useful later | Supports more detailed playstyle characterization |
| Creator/mapper | Useful later | May support display and creator preference signals |
| Target user's score on a candidate outside top plays | Useful later | Helps avoid presenting already-played maps as discoveries |
| Mod-adjusted beatmap attributes | Unknown | Important conceptually, but representation and source require research |
| Users associated with or ranked on a beatmap | Unknown and research-critical | May be required to build a similar-user candidate pool |

Data should be added only when a ticket verifies its source, meaning, nullability, and use in an actual query or feature.

## Similar-player discovery feasibility

The largest unresolved system question is how to obtain a useful candidate pool of other users. The current implementation can fetch a known username and that user's top plays; it does not discover users from a beatmap or maintain a population dataset.

Possible directions to research include leaderboard users on shared beatmaps, an externally seeded set of users, or a progressively built local dataset. Another osu! API-supported path may exist, but none is claimed here without verification. This deserves a dedicated research ticket before similarity implementation or scale assumptions are made.

## Later experimental metrics

Alphaosu is only a reference point for possible future product questions, not a design to copy. Later experiments might consider current PP on a map, predicted PP, PP gain potential, probability of entering top plays, record-improvement probability, or map difficulty/value indicators.

These metrics are not MVP requirements and must not shape the initial schema beyond reusing already justified raw user, play, and beatmap evidence. Their definitions, training/evaluation data, and accuracy would each require separate evidence.

## Initial recommendation MVP boundary

A smallest transparent recommendation experiment would:

1. Fetch and persist the target user's ordered top 100.
2. Establish a candidate pool of other users through a separately verified discovery mechanism.
3. Persist or obtain those users' ordered top plays.
4. Compare shared beatmap IDs using a simple, inspectable similarity signal.
5. Select maps from similar users that are absent from the target user's top plays.
6. Rank candidates using limited evidence such as overlap strength, position, mods, and available map attributes.
7. Return simple evidence explaining the recommendation.

This requires stable user and beatmap IDs, current ordered top-play relationships, score evidence, mods, available map attributes, fetch times, and a verified source for candidate users. It does not require stored similarity scores or recommendation rows.

## Explicitly not stored yet

- Recommendation results or explanations.
- Similar-user relationships or similarity scores.
- Aggregate player statistics or preference vectors.
- Cached API tokens or raw complete osu! JSON responses.
- Historical snapshots.
- Search history.
- Predicted PP, probabilities, or model outputs.
- Fields from unverified enrichment sources.

## Unresolved questions

- How should similar-user candidates be discovered efficiently and within verified API capabilities?
- How much beatmap enrichment is necessary for the first useful recommendation?
- Should top-play position be persisted directly during ordered ingestion? The current recommendation is yes, but real persistence behavior must validate it.
- When, if ever, do historical snapshots become necessary?
- How should raw versus mod-adjusted AR, BPM, star rating, and other attributes be represented?
- When should each category of external data be refreshed?
- What is the first similarity formula worth testing and how will usefulness be evaluated?
- How should already-played but non-top-play maps be detected later?
- How should users with sparse or empty top-play data be handled?
