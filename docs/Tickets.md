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
| T0042 | Discovery-only provenance and supporter-structure analysis | Current / complete |

No detailed tickets beyond T0042 are defined yet. T0043 must be chosen only after reviewing the provenance diagnostic. No production recommendation ranking has been selected.

T0040's 25 new live runs produced 13 discovery-only held-out positives: 7 improved, 4 worsened, and 2 were unchanged under star-only tie-breaking. No positive crossed a measured recall cutoff, so the experimental order remains unadopted.

T0041 derived supporting-player top-play positions from the existing ordered hydrated evidence without extra requests. Across 25 live splits it found 10 discovery-only positives: 2 improved, 7 worsened, and 1 was unchanged. No positive crossed a measured recall cutoff, so the experimental order remains unadopted.

T0042 described the same evaluation region without reranking. Nine of ten positives were single-support and nine were recurring-only; the sole one-hit positive was an improving T0041 observation, while all seven T0041 regressions were recurring-only single-support observations. These small descriptive counts do not establish provenance as ranking evidence.
