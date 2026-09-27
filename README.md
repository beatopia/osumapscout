# osu! Map Scout

A web app that recommends osu!standard maps based on a player's top plays and the maps played by similar users.

## How It Works

Given an osu! username, the app:

1. Fetches the player's profile and top plays.
2. Analyzes things like mods, star rating, AR, and BPM.
3. Finds similar players using overlap between top plays.
4. Looks at maps those players perform well on.
5. Filters out maps already in the target player's top plays.
6. Ranks the remaining maps using collaborative and playstyle evidence.

## Notes

- osu!standard only
- Uses the official osu! API v2
- API credentials are loaded from environment variables and should never be committed