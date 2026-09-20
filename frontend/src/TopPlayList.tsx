export interface TopPlay {
  score_id: number | null;
  beatmap_id: number;
  beatmapset_id: number | null;
  artist: string | null;
  title: string | null;
  difficulty_name: string | null;
  performance_points: number | null;
  accuracy: number | null;
  grade: string | null;
  mods: string[];
  max_combo: number | null;
  played_at: string | null;
  star_rating: number | null;
  approach_rate: number | null;
  bpm: number | null;
}

export interface TopPlaysResponse {
  username: string;
  count: number;
  top_plays: TopPlay[];
}

function isNullableNumber(value: unknown): value is number | null {
  return value === null || typeof value === "number";
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isTopPlay(value: unknown): value is TopPlay {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const play = value as Record<string, unknown>;
  return (
    isNullableNumber(play.score_id) &&
    typeof play.beatmap_id === "number" &&
    isNullableNumber(play.beatmapset_id) &&
    isNullableString(play.artist) &&
    isNullableString(play.title) &&
    isNullableString(play.difficulty_name) &&
    isNullableNumber(play.performance_points) &&
    isNullableNumber(play.accuracy) &&
    isNullableString(play.grade) &&
    Array.isArray(play.mods) &&
    play.mods.every((mod) => typeof mod === "string") &&
    isNullableNumber(play.max_combo) &&
    isNullableString(play.played_at) &&
    isNullableNumber(play.star_rating) &&
    isNullableNumber(play.approach_rate) &&
    isNullableNumber(play.bpm)
  );
}

export function isTopPlaysResponse(value: unknown): value is TopPlaysResponse {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const response = value as Record<string, unknown>;
  return (
    typeof response.username === "string" &&
    typeof response.count === "number" &&
    Array.isArray(response.top_plays) &&
    response.top_plays.every(isTopPlay)
  );
}

interface TopPlayListProps {
  result: TopPlaysResponse;
}

function TopPlayList({ result }: TopPlayListProps) {
  if (result.top_plays.length === 0) {
    return <p className="empty-message">No top plays were returned for this user.</p>;
  }

  return (
    <ol className="top-play-list">
      {result.top_plays.map((play, index) => {
        const artist = play.artist ?? "Unknown artist";
        const title = play.title ?? `Beatmap ${play.beatmap_id}`;
        const difficulty = play.difficulty_name
          ? ` [${play.difficulty_name}]`
          : "";
        const mods = play.mods.length > 0 ? play.mods.join(" ") : "NM";

        return (
          <li
            className="top-play"
            key={play.score_id ?? `${play.beatmap_id}-${index}`}
          >
            <span className="play-position">#{index + 1}</span>
            <div className="play-content">
              <h2>
                {artist} - {title}
                {difficulty}
              </h2>

              <div className="play-summary">
                <strong>
                  {play.performance_points !== null
                    ? `${play.performance_points.toFixed(2)}pp`
                    : "PP unavailable"}
                </strong>
                <span className="mods">{mods}</span>
                <span>
                  {play.accuracy !== null
                    ? `${(play.accuracy * 100).toFixed(2)}%`
                    : "Accuracy unavailable"}
                </span>
                {play.grade && <span>Grade {play.grade}</span>}
                {play.max_combo !== null && <span>{play.max_combo}x combo</span>}
              </div>

              {(play.star_rating !== null ||
                play.approach_rate !== null ||
                play.bpm !== null) && (
                <div className="map-attributes">
                  {play.star_rating !== null && (
                    <span>{play.star_rating.toFixed(2)}★</span>
                  )}
                  {play.approach_rate !== null && (
                    <span>AR {play.approach_rate}</span>
                  )}
                  {play.bpm !== null && <span>{play.bpm} BPM</span>}
                </div>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

export default TopPlayList;
