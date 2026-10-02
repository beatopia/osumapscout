import { CSSProperties } from "react";

import {
  compareToPreference,
  comparisonLabels,
  PreferenceBounds,
} from "./statComparison";

export interface Recommendation {
  rank: number;
  beatmap_id: number;
  artist: string | null;
  title: string | null;
  difficulty_name: string | null;
  beatmapset_id: number | null;
  cover_url: string | null;
  star_rating: number | null;
  adjusted_star_rating: number | null;
  approach_rate: number | null;
  bpm: number | null;
  suggested_mods: string[];
  support_count: number;
  best_supporting_player_rank: number;
  attributes_within_iqr_count: number;
  why_recommended: string;
}

export interface RecommendationContext {
  discovered_candidate_users: number;
  hydrated_candidate_users: number;
  ranking_similar_players: number;
  discovery_similar_players: number;
  candidate_map_count: number;
  returned_recommendation_count: number;
}

export interface RecommendationRequests {
  profile_requests: number;
  target_top_play_requests: number;
  leaderboard_requests: number;
  candidate_top_play_requests: number;
  beatmap_attribute_requests: number;
}

export interface RecommendationPreferences {
  star_rating: PreferenceBounds | null;
  approach_rate: PreferenceBounds | null;
  bpm: PreferenceBounds | null;
}

export interface RecommendationsResponse {
  target_username: string;
  target_user_id: number;
  recommendations: Recommendation[];
  context: RecommendationContext;
  requests: RecommendationRequests;
  preferences: RecommendationPreferences;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isNullableNumber(value: unknown): value is number | null {
  return value === null || typeof value === "number";
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function hasNumericFields(
  value: Record<string, unknown>,
  fields: readonly string[],
): boolean {
  return fields.every((field) => typeof value[field] === "number");
}

function isRecommendation(value: unknown): value is Recommendation {
  if (!isRecord(value)) {
    return false;
  }
  return (
    hasNumericFields(value, [
      "rank",
      "beatmap_id",
      "support_count",
      "best_supporting_player_rank",
      "attributes_within_iqr_count",
    ]) &&
    isNullableString(value.artist) &&
    isNullableString(value.title) &&
    isNullableString(value.difficulty_name) &&
    isNullableNumber(value.beatmapset_id) &&
    isNullableString(value.cover_url) &&
    isNullableNumber(value.star_rating) &&
    isNullableNumber(value.adjusted_star_rating) &&
    isNullableNumber(value.approach_rate) &&
    isNullableNumber(value.bpm) &&
    Array.isArray(value.suggested_mods) &&
    value.suggested_mods.every((mod) => typeof mod === "string") &&
    typeof value.why_recommended === "string"
  );
}

export function isRecommendationsResponse(
  value: unknown,
): value is RecommendationsResponse {
  if (
    !isRecord(value) ||
    !isRecord(value.context) ||
    !isRecord(value.requests) ||
    !isRecord(value.preferences)
  ) {
    return false;
  }
  return (
    typeof value.target_username === "string" &&
    typeof value.target_user_id === "number" &&
    Array.isArray(value.recommendations) &&
    value.recommendations.every(isRecommendation) &&
    hasNumericFields(value.context, [
      "discovered_candidate_users",
      "hydrated_candidate_users",
      "ranking_similar_players",
      "discovery_similar_players",
      "candidate_map_count",
      "returned_recommendation_count",
    ]) &&
    hasNumericFields(value.requests, [
      "profile_requests",
      "target_top_play_requests",
      "leaderboard_requests",
      "candidate_top_play_requests",
      "beatmap_attribute_requests",
    ])
    && isNullableBounds(value.preferences.star_rating)
    && isNullableBounds(value.preferences.approach_rate)
    && isNullableBounds(value.preferences.bpm)
  );
}

function isNullableBounds(value: unknown): value is PreferenceBounds | null {
  return value === null || (
    isRecord(value) &&
    hasNumericFields(value, ["first_quartile", "median", "third_quartile"])
  );
}

interface RecommendationListProps {
  result: RecommendationsResponse;
}

function RecommendationList({ result }: RecommendationListProps) {
  if (result.recommendations.length === 0) {
    return <p className="empty-message">No recommendations found.</p>;
  }

  return (
    <section className="recommendations" aria-labelledby="recommendations-heading">
      <div className="recommendations-heading-row">
        <div>
          <p className="eyebrow">Map recommendations</p>
          <h2 id="recommendations-heading">
            Recommendations for {result.target_username}
          </h2>
        </div>
        <p>{result.recommendations.length} maps found</p>
      </div>
      <p className="generation-context">
        Generated from {result.context.candidate_map_count} candidate maps.
      </p>
      <div className="comparison-legend" aria-label="Map attribute color key">
        {(["typical", "outside", "unusually-high", "unusually-low"] as const).map(
          (category) => (
            <span key={category} className={`comparison-${category}`}>
              <span aria-hidden="true">●</span> {comparisonLabels[category]}
            </span>
          ),
        )}
      </div>

      <ol className="recommendation-list">
        {result.recommendations.map((recommendation) => {
          const artist = recommendation.artist ?? "Unknown artist";
          const title = recommendation.title ?? `Beatmap ${recommendation.beatmap_id}`;
          const hasAttributes =
            recommendation.star_rating !== null ||
            recommendation.approach_rate !== null ||
            recommendation.bpm !== null;
          const displayedStar =
            recommendation.adjusted_star_rating ?? recommendation.star_rating;
          const mods = recommendation.suggested_mods.length > 0
            ? recommendation.suggested_mods.join("")
            : "NM";
          const cardStyle = recommendation.cover_url
            ? ({ "--cover-image": `url("${recommendation.cover_url}")` } as CSSProperties)
            : undefined;

          return (
            <li className="recommendation-card" key={recommendation.beatmap_id} style={cardStyle}>
              <span className="recommendation-rank">#{recommendation.rank}</span>
              <div className="recommendation-content">
                <h3>
                  <a
                    href={`https://osu.ppy.sh/beatmaps/${recommendation.beatmap_id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {artist} - {title}
                  </a>
                </h3>
                {recommendation.difficulty_name && (
                  <p className="difficulty-name">[{recommendation.difficulty_name}]</p>
                )}
                <p className="suggested-mods">Suggested Mods: <strong>{mods}</strong></p>
                {hasAttributes && (
                  <div className="map-attributes">
                    {displayedStar !== null && (
                      <ComparedStat label={`${displayedStar.toFixed(2)}★`} value={displayedStar} bounds={result.preferences.star_rating} />
                    )}
                    {recommendation.approach_rate !== null && (
                      <ComparedStat label={`AR ${recommendation.approach_rate}`} value={recommendation.approach_rate} bounds={result.preferences.approach_rate} />
                    )}
                    {recommendation.bpm !== null && (
                      <ComparedStat label={`${recommendation.bpm} BPM`} value={recommendation.bpm} bounds={result.preferences.bpm} />
                    )}
                  </div>
                )}
                <p className="recommendation-reason">
                  {recommendation.why_recommended}
                </p>
                <p className="support-count">
                  {recommendation.support_count} similar {recommendation.support_count === 1 ? "player" : "players"}
                </p>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function ComparedStat({
  label,
  value,
  bounds,
}: {
  label: string;
  value: number;
  bounds: PreferenceBounds | null;
}) {
  const category = compareToPreference(value, bounds);
  const description = comparisonLabels[category];
  return (
    <span className={`compared-stat comparison-${category}`} title={description}>
      {label}<span className="visually-hidden"> — {description}</span>
    </span>
  );
}

export default RecommendationList;
