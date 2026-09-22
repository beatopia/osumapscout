# Similar-Player Discovery Research

## Status and problem

T0017 is research only. No candidate discovery, similarity metric, crawler, or recommendation behavior is implemented.

Candidate generation asks “who should we compare?” Similarity asks “which of those users resembles the target?” The application can fetch and persist a known user's current top plays, but it first needs a defensible source of other osu!standard user IDs. That source will bias every later similarity result regardless of the formula used.

## Current project constraints

- The database contains only users deliberately persisted through the existing command.
- A persisted user has a nullable global rank and current top-play relationships.
- The osu! client can fetch a profile by username and then up to 100 best scores.
- The current client obtains a token for each public operation. A bulk workflow would need bounded token reuse before its request count is practical; that is future implementation work.
- The existing schema has no discovery-run, candidate-source, similarity, or recommendation tables.
- The first experiment should be inspectable and bounded before queues, workers, caches, or crawling infrastructure are considered.

## Official osu! API capabilities

The current [osu!api v2 reference](https://osu.ppy.sh/docs/) documents these relevant public capabilities:

- `GET /rankings/{mode}/{type}` returns a current ranking. An osu!standard performance-ranking entry contains user statistics, including global rank, and a nested user object. The response has a cursor and an approximate total.
- `GET /beatmaps/{beatmap}/scores` returns the top scores for one beatmap. Scores identify their user, and this response context includes a user object.
- `GET /scores` returns up to 1,000 passed scores, ordered oldest to newest within the response. With no cursor it returns the most recent scores; its returned `cursor_string` can obtain newer scores later.
- `GET /users/{user}/scores/best` returns a user's best scores and accepts `limit` and `offset`.
- `GET /beatmaps` accepts multiple beatmap IDs, with a documented maximum of 50. This can reduce later metadata calls but does not batch user top-play requests or discover users.
- These endpoints use public OAuth. A client-credentials token is a guest token and includes an expiry.

The documentation calls itself a work in progress. Observed behavior must be verified in a prototype rather than treated as a permanent contract.

## Missing reverse-top-play lookup

The official API v2 reference documents user-best scores, beatmap leaderboards, rankings, and a global score feed. It does **not** document an endpoint equivalent to:

```text
beatmap X -> every user whose best/top-play list contains X
```

This is a conclusion from the documented public endpoints, not a claim about osu!'s private internal data. Consequently, `osumapscout` cannot directly turn one target top play into all users who share it in their top 100. It must obtain a bounded user population elsewhere, fetch or already possess those users' top plays, and build the relationship locally.

## Strategy A — Global rankings

### Documented capability

`GET /rankings/osu/performance` provides osu!standard performance-ranking entries. Each entry provides user identity and statistics such as global rank. The response exposes a cursor for traversal and an approximate total. Country, ranking filter, and variant filters are documented where applicable; an arbitrary numeric rank-range filter is not.

### Feasibility and bias

A bounded number of ranking responses could seed candidates without knowing usernames. Selecting users near a target's stored rank is plausible, but conversion from a rank to a cursor position is not documented. The endpoint documents cursor traversal, not random access to “ranks 10,000–40,000.” A prototype must establish whether a small traversal can reliably reach a target neighborhood; it must not assume page size or cursor encoding.

Leading pages strongly favor elite users. A broader region improves diversity but increases calls and still excludes unranked, inactive, or atypical users. Rank proximity is a coarse skill/activity prior, not evidence of shared maps or taste.

### Cost shape

If `R` ranking requests yield `C` unique IDs, discovery costs `R` requests. Later comparison costs about `C` user-best requests, plus profile requests when fields unavailable from ranking entries are required. Deduplicate before those calls.

## Strategy B — Beatmap leaderboards

### Documented capability

`GET /beatmaps/{beatmap}/scores` returns the top scores for one beatmap and identifies scoring users. The reference does not document `limit`, offset, page, or cursor parameters for this endpoint, nor promise a particular score count. Treat it as a finite top-leaderboard view, not all players of the map.

### Feasibility and bias

Combining leaderboard users for several target maps produces map-conditioned candidates. This is more target-related than a random global sample, but does **not** establish that the map is in those users' own top plays.

The pool favors leaderboard-level players, popular maps or mod combinations, and specialists. A target outside that skill band may receive poor peers. Popular maps can create duplicates while still exposing only their strongest scorers; obscure maps may produce very small pools.

### Cost shape

For `M` selected maps, discovery costs about `M` leaderboard requests and yields `C` unique users after deduplication. Later comparison adds roughly `C` best-score requests and perhaps `C` profile requests. Undocumented pagination limits deliberate widening.

## Strategy C — Global score feed

### Documented capability

`GET /scores` supplies up to 1,000 passed scores. Without a cursor it starts from recent scores; later polling can pass the returned cursor for newer scores. The response order is oldest to newest.

### Feasibility and bias

One response can cheaply seed recently active user IDs, but score recency has little inherent relationship to the target's skill, mods, or preferences. Multiple scores from active users require deduplication, and time of day or events affect the sample.

It may later grow a background population where recent activity is intentional. It is too noisy as the primary target-specific MVP source, and continuous consumption would add ingestion operations beyond current needs.

### Cost shape

One feed request returns at most 1,000 scores, not necessarily 1,000 users. Comparing `C` deduplicated users still adds about `C` best-score requests and possibly profiles. Cursor polling creates an ongoing workload.

## Strategy D — Persisted osumapscout users

The database can provide candidates without upstream discovery calls. Every deliberately persisted user already has the relationship data later similarity work needs.

- **5 users:** only a plumbing demonstration; results are fragile.
- **50 users:** a small manual experiment, dominated by who tested the product.
- **500 users:** potentially useful if varied and fresh, with substantial selection bias.
- **50,000 users:** meaningful, but refresh cost, retention, indexing, and policy become product concerns.

This source has zero discovery API cost and grows organically, but has a severe launch cold start and a product-user bias. Public profiles and scores do not justify unlimited retention: the product should be transparent, store only justified fields, and define deletion and refresh practices before scale.

Local users are valuable in a hybrid and improve over time. They are insufficient alone at launch.

## Strategy E — Controlled crawl expansion

```text
known users -> selected top maps -> map leaderboards -> new users -> best scores
```

For `U` frontier users and `M` maps per user, one layer can require up to `U × M` leaderboard calls before fetching new users' top plays. Duplicate maps and users reduce unique results but only avoid calls when deduplicated and cached first. Repeated layers magnify leaderboard bias and drift from the target.

A responsible experiment needs hard limits on depth, frontier size, maps, calls, elapsed time, retries, freshness, and deduplication. That is operationally a crawler. Official API guidance discourages mass harvesting and points seed/sample use toward `data.ppy.sh`, so crawling is not justified for the MVP.

## Strategy F — Public datasets

### Official data.ppy.sh samples

The official [data.ppy.sh index](https://data.ppy.sh/) currently lists dated osu!standard performance archives for random 10,000-user and top 1,000/top 10,000 samples, osu! beatmap files, and some SQL extracts. Monthly-looking filenames exist, but the index does not promise a publication schedule, stable schema, or indefinite retention. Archives were not downloaded, so their exact fields are not asserted.

The [license notice](https://data.ppy.sh/LICENCE.txt) says this data is intended for statistical analysis and subsystem testing. It explicitly does not grant production deployment or public-exposure permission and asks prospective public users to contact osu!. It is credible for offline feasibility testing, but not a production dependency or bundle without permission and a reviewed import design.

### Community and research datasets

No community/Kaggle-style option examined combined clearly current top-100 relationships, dependable refreshes, stable schema, and production-compatible terms strongly enough to recommend. Such datasets can be stale, disappear, cover selected ranks or periods, and add import maintenance. A later experiment may assess a specifically named dataset with its schema and license; T0017 does not endorse an unspecified source.

## Strategy G — Hybrid candidate generation

```text
persisted local users
+ bounded official performance-ranking users
+ optional users from a few selected map leaderboards
-> exclude target and deduplicate
-> enforce one total cap
```

Local users are cheap and improve organically. Rankings solve launch cold start with a documented population source. Leaderboards can add a map-conditioned signal, but elite-score bias and undocumented result count make them better as a later controlled experiment.

Every source needs limits, provenance, bias explanation, and failure behavior. The MVP should implement only local plus bounded rank-based acquisition while preserving the option to compare a leaderboard branch later.

## API usage and scaling considerations

The official documentation asks clients to remain at or below **60 requests per minute (generally one per second)**. It recommends caching/reuse, irregular polling, and exponential backoff, and describes repeated per-user/per-beatmap polling and mass harvesting as incorrect usage. Serious long-term use should be discussed with osu!.

- Reuse a client-credentials token until expiry rather than acquiring one per item in a bounded batch.
- Deduplicate IDs before requests and reuse fresh persisted top plays.
- Apply a hard cap before fetching candidate top plays.
- A 100-candidate comparison needs about 100 best-score requests when profiles are unnecessary or known. At the documented guidance rate, this cannot be an instant interactive fan-out.
- Using the current profile-then-top-play workflow for 100 new candidates would take roughly 200 data requests, plus avoidable authentication requests. Later acquisition should accept numeric IDs and separate discovery from ingestion.
- Beatmap metadata batches accept up to 50 IDs; no documented equivalent batches many users' best-score lists.

These are call-shape estimates, not throughput promises. Retries, token calls, cache hits, and actual result sizes change observed cost.

## Comparison

API cost below includes discovery and the later work needed to hydrate a useful pool; complexity includes operations as well as endpoint code.

| Strategy | Target relevance | Cold start | API cost | Main bias | Complexity | Freshness / growth |
| --- | --- | --- | --- | --- | --- | --- |
| Global rankings | Low–medium | Good | Medium | Ranked, active, sampled skill bands | Medium | Current but not organic |
| Beatmap leaderboards | Medium | Good | Medium–high | Elite scores, popular maps, specialists | Medium | Current, endpoint-limited |
| Global score feed | Low | Good | Low discovery; medium–high hydration | Recently active users and time of day | Medium if continuous | Very fresh; grows rapidly |
| Persisted users | Variable | Poor initially | Low | Product users and operator choices | Low | Organic; refresh-policy dependent |
| Outward crawl | Medium, degrading with depth | Good | High and multiplicative | Leaderboard-connected users/maps | High | Grows with operational burden |
| Official samples | Low–medium | Good offline | No live discovery after import | Snapshot construction and date | High import/terms burden | Dated; permission needed for production |
| Bounded hybrid | Medium | Good | Medium and capped | Combined source biases | Medium | Improves with local growth |

## Recommended MVP direction

Use a **bounded hybrid of already-persisted users plus an official performance-ranking sample**, deduplicated and capped before top-play acquisition.

1. Start with eligible persisted users other than the target, up to a configured cap.
2. If the pool is short, use a small fixed maximum of `GET /rankings/osu/performance` cursor requests.
3. Prefer a rank neighborhood only if the prototype proves a safe way to reach it; otherwise report the limitation rather than claiming rank-nearby sampling.
4. Return candidate identity and provenance only. Do not fetch top plays or calculate similarity in the same ticket.

This reuses the database, supplies an official cold-start source, bounds upstream work, and keeps discovery independently testable. It does not mistake rank proximity for similarity.

## Deferred alternatives

- Add leaderboard candidates only after observing result counts and testing usefulness for non-elite targets.
- Use the score feed only for an approved background-population experiment.
- Do not crawl until bounded sources demonstrably fail and osu! usage expectations are addressed.
- Use official dumps offline only unless production permission and an import plan exist.
- Reassess named community datasets only with current schema, provenance, update, and license evidence.

## Implications for the current schema

The current schema is sufficient for a transient prototype: target `global_rank` can inform selection when non-null, existing IDs provide the local pool, and ranking discoveries can remain in memory.

T0018 should not create placeholder `users` rows merely to remember candidate IDs because that model represents fetched profile state and requires fields discovery may not authoritatively populate. No migration is needed. A discovery-run/candidate observation model may become justified for durable provenance or scheduling, but it is premature. Similarity and recommendation tables remain unjustified.

## Proposed T0018

**T0018 — Bounded candidate-user discovery prototype**

Minimum success criteria:

- Given one persisted osu!standard target, return up to 100 unique other user IDs.
- Use persisted users first and the documented performance ranking only to fill remaining capacity.
- Exclude the target and deduplicate across sources.
- Attach `local` or `ranking` provenance.
- Use an explicit request budget; three ranking requests is the recommended starting cap.
- Handle null target rank and exhausted/no ranking results explicitly.
- Record observed ranking result size and cursor behavior instead of assuming undocumented page semantics.
- Do not fetch candidate top plays, calculate similarity, persist discovery results, or recommend maps.

This proves bounded acquisition. A later ticket can decide whether to hydrate candidates and evaluate overlap.

## Open questions

- Can a small cursor budget reach a useful neighborhood around an arbitrary rank?
- What observed ranking result size and cursor behavior are stable enough to use?
- What local freshness threshold should later comparison require?
- How should unranked targets avoid defaulting entirely to elite pages?
- Does a small leaderboard branch improve relevance enough to justify its bias and calls?
- What deletion and retention policy is needed before organic storage grows?
- Should osu! be contacted before systematic production candidate acquisition?

## Sources

- [Official osu!api v2 documentation](https://osu.ppy.sh/docs/) — authentication, endpoint contracts, response objects, batching, and usage guidance; last updated September 16, 2026 when researched.
- [Official osu!api wiki overview](https://osu.ppy.sh/wiki/en/osu%21api) — official API background and documentation entry point.
- [Official data.ppy.sh index](https://data.ppy.sh/) — dated sample archives and SQL extracts.
- [Official data.ppy.sh license notice](https://data.ppy.sh/LICENCE.txt) — analysis/testing intent and production-use warning.
