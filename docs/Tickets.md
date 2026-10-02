# Ticket Tracker

This is a rough, incremental roadmap. Ticket scope and ordering may change when API behavior and implementation findings provide better information. Do not begin a later ticket as part of an earlier one.

| Ticket | Title | Status |
| --- | --- | --- |
| T0001 | Repository/documentation skeleton | Complete |
| T0002 | FastAPI application skeleton | Complete |
| T0003 | osu! API authentication/client credentials | Complete |
| T0004 | Fetch basic osu! user profile | Complete |
| T0005 | Fetch user top plays | Complete |
| T0006 | Expose normalized top-play backend endpoint | Complete |
| T0007 | React/Vite frontend skeleton | Complete |
| T0008 | Username search flow | Complete |
| T0009 | Display top plays | Complete |
| T0010 | Recommendation data requirements and persistence design | Complete |
| T0011 | PostgreSQL development setup | Complete |
| T0012 | Minimal persistence schema and migrations | Complete |
| T0013 | Persist fetched users and top plays | Complete |
| T0014 | Basic player statistics | Complete |
| T0015 | Player analysis endpoint | Complete |
| T0016 | Player analysis UI | Complete |
| T0017 | Similar-player discovery feasibility research | Complete |
| T0018 | Bounded candidate-user discovery prototype | Complete |
| T0019 | Candidate top-play hydration prototype | Complete |
| T0020 | Top-play overlap similarity experiment | Complete |
| T0021 | Target-map leaderboard candidate source experiment | Complete |
| T0022 | Evaluate target-map candidates with top-play overlap | Complete |
| T0023 | One-hit candidate overlap baseline | Complete |
| T0024 | Full-pool stratified candidate baseline | Complete |
| T0025 | Budgeted similar-player candidate ranking experiment | Complete |
| T0026 | Similar-player candidate-map extraction experiment | Complete |
| T0027 | Candidate-map evidence ranking experiment | Complete |
| T0028 | Candidate-map preference evidence experiment | Complete |
| T0029 | Held-out top-play recovery experiment | Complete |
| T0030 | Multi-split held-out recovery evaluation | Complete |
| T0031 | Preference-aware candidate-map ranking experiment | Complete |
| T0032 | Candidate acquisition coverage analysis | Complete |
| T0033 | Acquisition budget sensitivity experiment | Complete |
| T0034 | Selected-player expansion rank-impact analysis | Complete |
| T0035 | Discovery / ranking evidence separation experiment | Complete |
| T0036 | Discovery-only candidate placement analysis | Complete |
| T0037 | Discovery-only tie-group analysis | Complete |
| T0038 | Cross-target discovery-tie validation | Complete |
| T0039 | Single-field continuous tie-break experiment | Complete |
| T0040 | Expanded star tie-break validation | Complete |
| T0041 | Supporting-player top-play-position experiment | Complete |
| T0042 | Discovery-only provenance and supporter-structure analysis | Complete |
| T0043 | Supporter top-play-position prevalence analysis | Complete |
| T0044 | Production recommendation service | Complete |
| T0045 | Recommendation UI | Complete |
| T0046 | Recommendation UX and map enrichment | Complete |
| T0047 | Unified player view and recommendation support details | Complete |
| T0048 | Target-oriented recommendation mod semantics and peer diagnostic | Complete |
| T0049 | Similar-player compatibility selection experiment | Complete |
| T0050 | Candidate-user acquisition experiment | Complete |
| T0051 | Recommendation card UX polish | Current / complete |

No detailed tickets beyond T0051 are defined yet. A production change requires a separately reviewed ticket.

T0040's 25 new live runs produced 13 discovery-only held-out positives: 7 improved, 4 worsened, and 2 were unchanged under star-only tie-breaking. No positive crossed a measured recall cutoff, so the experimental order remains unadopted.

T0041 derived supporting-player top-play positions from the existing ordered hydrated evidence without extra requests. Across 25 live splits it found 10 discovery-only positives: 2 improved, 7 worsened, and 1 was unchanged. No positive crossed a measured recall cutoff, so the experimental order remains unadopted.

T0042 described the same evaluation region without reranking. Nine of ten positives were single-support and nine were recurring-only; the sole one-hit positive was an improving T0041 observation, while all seven T0041 regressions were recurring-only single-support observations. These small descriptive counts do not establish provenance as ranking evidence.

T0043 measured raw positive prevalence by the best supporter's top-play position without reranking. The five fixed buckets were non-monotonic, and the recurring-only single-support stratum was also non-monotonic. The live fallback observed 12 positives among 6,460 eligible candidate observations; this sparse, target-dependent evidence does not establish supporter position as a ranking signal.

T0044 freezes the experimentally supported hybrid policy as an application service. The top ten similar players provide discovery and ranking evidence, players 11–15 add discovery-only maps, and the existing preference-aware ordering ranks the hybrid pool. A public endpoint returns bounded typed results, deterministic explanations, context, and external request accounting without persisting recommendations.

T0045 connects the existing shared username flow to the production recommendation endpoint. It displays a bounded 20-map result with map attributes, support, deterministic explanations, responsive loading/empty/error states, and no ranking controls or experimental terminology.

T0046 reorganizes the player page around recommendations, adds collapsible top plays and playstyle wording, and enriches returned maps with covers, links, deterministic suggested mods, optional mod-adjusted star ratings, and target-IQR comparison labels. Enrichment is display-only and does not change recommendation membership or order.

T0047 replaces separate player actions with one Search flow that generates recommendations and then reads the freshly persisted analysis. Recommendation rows expose the exact eligible supporting users, similarity ranks, and map-specific mods without extra osu! requests or ranking changes.

T0048 separates supporter mods from target-oriented Suggested Mods. Suggestions and returned-map difficulty enrichment use the target's dominant exact top-play combination, while supporter disclosures retain factual supporter mods. It also adds descriptive similar-player mod/PP diagnostics without changing selection or ranking.

T0049 compares baseline, mod-first, PP-first, and compatibility-first selection over the same hydrated 25-user pool. Across 15 target/split runs, baseline recovered 81/150 held-out observations versus 76, 74, and 73 respectively; compatibility views improved descriptive compatibility but generally reduced collaborative overlap and recovery. No production view was adopted.

T0050 compares unchanged baseline acquisition with requested-mod leaderboard, bounded performance-ranking, and fixed mixed sources. Requested-mod acquisition recovered 85/150 observations versus baseline's 81/150, but reduced early recall. The performance endpoint exposed only the top 10,000, preventing a true neighborhood for lower-ranked targets. No production source was adopted.

T0051 makes the existing recommendation cards more compact and data-first. Cover art now fills each card behind a dark readability overlay, long titles clamp to two lines, base AR/BPM labels are simplified without inventing adjusted values, and one collapsed `Why this map?` disclosure contains both the concise reason and supporting-player evidence. Recommendation behavior is unchanged.
