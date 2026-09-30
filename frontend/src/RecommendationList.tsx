export interface Recommendation {
  rank: number;
  beatmap_id: number;
  artist: string | null;
  title: string | null;
  difficulty_name: string | null;
  star_rating: number | null;
  approach_rate: number | null;
  bpm: number | null;
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
}

export interface RecommendationsResponse {
  target_username: string;
  target_user_id: number;
  recommendations: Recommendation[];
  context: RecommendationContext;
  requests: RecommendationRequests;
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
    isNullableNumber(value.star_rating) &&
    isNullableNumber(value.approach_rate) &&
    isNullableNumber(value.bpm) &&
    typeof value.why_recommended === "string"
  );
}

export function isRecommendationsResponse(
  value: unknown,
): value is RecommendationsResponse {
  if (!isRecord(value) || !isRecord(value.context) || !isRecord(value.requests)) {
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
    ])
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

      <ol className="recommendation-list">
        {result.recommendations.map((recommendation) => {
          const artist = recommendation.artist ?? "Unknown artist";
          const title = recommendation.title ?? `Beatmap ${recommendation.beatmap_id}`;
          const hasAttributes =
            recommendation.star_rating !== null ||
            recommendation.approach_rate !== null ||
            recommendation.bpm !== null;

          return (
            <li className="recommendation-card" key={recommendation.beatmap_id}>
              <span className="recommendation-rank">#{recommendation.rank}</span>
              <div className="recommendation-content">
                <h3>{artist} - {title}</h3>
                {recommendation.difficulty_name && (
                  <p className="difficulty-name">[{recommendation.difficulty_name}]</p>
                )}
                {hasAttributes && (
                  <div className="map-attributes">
                    {recommendation.star_rating !== null && (
                      <span>{recommendation.star_rating.toFixed(2)}★</span>
                    )}
                    {recommendation.approach_rate !== null && (
                      <span>AR {recommendation.approach_rate}</span>
                    )}
                    {recommendation.bpm !== null && (
                      <span>{recommendation.bpm} BPM</span>
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

export default RecommendationList;
