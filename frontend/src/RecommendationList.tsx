import { useState } from "react";

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
  supporting_players: SupportingPlayer[];
  best_supporting_player_rank: number;
  attributes_within_iqr_count: number;
  why_recommended: string;
}

export interface SupportingPlayer {
  user_id: number;
  username: string | null;
  similarity_rank: number;
  mods: string[];
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

export interface TargetModCombination {
  mods: string[];
  count: number;
  share: number;
}

export interface TargetRecommendationProfile {
  primary_mods: string[];
  mod_distribution: TargetModCombination[];
  performance_points: PreferenceBounds | null;
  actual_play_star_rating: PreferenceBounds | null;
}

export interface RecommendationsResponse {
  target_username: string;
  target_user_id: number;
  recommendations: Recommendation[];
  context: RecommendationContext;
  requests: RecommendationRequests;
  preferences: RecommendationPreferences;
  target_profile: TargetRecommendationProfile;
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
    Array.isArray(value.supporting_players) &&
    value.supporting_players.every(isSupportingPlayer) &&
    value.supporting_players.length === value.support_count &&
    typeof value.why_recommended === "string"
  );
}

function isSupportingPlayer(value: unknown): value is SupportingPlayer {
  return isRecord(value) &&
    typeof value.user_id === "number" &&
    isNullableString(value.username) &&
    typeof value.similarity_rank === "number" &&
    Array.isArray(value.mods) &&
    value.mods.every((mod) => typeof mod === "string");
}

export function isRecommendationsResponse(
  value: unknown,
): value is RecommendationsResponse {
  if (
    !isRecord(value) ||
    !isRecord(value.context) ||
    !isRecord(value.requests) ||
    !isRecord(value.preferences) ||
    !isRecord(value.target_profile)
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
    && Array.isArray(value.target_profile.primary_mods)
    && value.target_profile.primary_mods.every((mod) => typeof mod === "string")
    && Array.isArray(value.target_profile.mod_distribution)
    && value.target_profile.mod_distribution.every(isTargetModCombination)
    && isNullableBounds(value.target_profile.performance_points)
    && isNullableBounds(value.target_profile.actual_play_star_rating)
  );
}

function isTargetModCombination(value: unknown): value is TargetModCombination {
  return isRecord(value) &&
    Array.isArray(value.mods) &&
    value.mods.every((mod) => typeof mod === "string") &&
    typeof value.count === "number" &&
    typeof value.share === "number";
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
          <h2 id="recommendations-heading">
            Map Recommendations for {result.target_username}
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
          return (
            <li className="recommendation-card" key={recommendation.beatmap_id}>
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
                      <ComparedStat label={`Base AR ${recommendation.approach_rate}`} value={recommendation.approach_rate} bounds={result.preferences.approach_rate} />
                    )}
                    {recommendation.bpm !== null && (
                      <ComparedStat label={`Base ${recommendation.bpm} BPM`} value={recommendation.bpm} bounds={result.preferences.bpm} />
                    )}
                  </div>
                )}
                <p className="recommendation-reason">
                  {recommendation.why_recommended}
                </p>
                <SupportDisclosure recommendation={recommendation} />
              </div>
              {recommendation.cover_url && (
                <img className="recommendation-cover" src={recommendation.cover_url} alt="" loading="lazy" />
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function SupportDisclosure({ recommendation }: { recommendation: Recommendation }) {
  const [isOpen, setIsOpen] = useState(false);
  const panelId = `supporters-${recommendation.beatmap_id}`;
  const noun = recommendation.support_count === 1 ? "player" : "players";
  return (
    <div className="support-disclosure">
      <button type="button" aria-expanded={isOpen} aria-controls={panelId} onClick={() => setIsOpen((open) => !open)}>
        Recommended by {recommendation.support_count} similar {noun}
        <span aria-hidden="true"> {isOpen ? "▾" : "▸"}</span>
      </button>
      {isOpen && (
        <ul id={panelId} className="supporting-player-list">
          {recommendation.supporting_players.map((player) => {
            const mods = player.mods.length > 0 ? player.mods.join("") : "NM";
            return (
              <li key={player.user_id}>
                <span>#{player.similarity_rank} similar</span>
                <a href={`https://osu.ppy.sh/users/${player.user_id}`} target="_blank" rel="noopener noreferrer">
                  {player.username ?? `User ${player.user_id}`}
                </a>
                <span className="mods">{mods}</span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
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
