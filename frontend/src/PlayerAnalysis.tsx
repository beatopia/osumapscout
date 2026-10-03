import type { ReactNode } from "react";

import ModBadges from "./ModBadges";
import type { RecommendationPreferences, TargetRecommendationProfile } from "./RecommendationList";

export interface ModCombinationCount {
  mods: string[];
  count: number;
}

export interface IndividualModCount {
  mod: string;
  count: number;
}

export interface PlayerAnalysisResponse {
  user_id: number;
  username: string;
  top_play_count: number;
  average_pp: number | null;
  average_accuracy: number | null;
  average_star_rating: number | null;
  average_approach_rate: number | null;
  average_bpm: number | null;
  exact_mod_combinations: ModCombinationCount[];
  individual_mods: IndividualModCount[];
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isNullableNumber(value: unknown): value is number | null {
  return value === null || (typeof value === "number" && Number.isFinite(value));
}

function isModCombinationCount(value: unknown): value is ModCombinationCount {
  if (!isObject(value)) {
    return false;
  }

  return (
    Array.isArray(value.mods) &&
    value.mods.every((mod) => typeof mod === "string") &&
    typeof value.count === "number" &&
    Number.isInteger(value.count) &&
    value.count >= 0
  );
}

function isIndividualModCount(value: unknown): value is IndividualModCount {
  if (!isObject(value)) {
    return false;
  }

  return (
    typeof value.mod === "string" &&
    typeof value.count === "number" &&
    Number.isInteger(value.count) &&
    value.count >= 0
  );
}

export function isPlayerAnalysisResponse(
  value: unknown,
): value is PlayerAnalysisResponse {
  if (!isObject(value)) {
    return false;
  }

  return (
    typeof value.user_id === "number" &&
    Number.isInteger(value.user_id) &&
    typeof value.username === "string" &&
    typeof value.top_play_count === "number" &&
    Number.isInteger(value.top_play_count) &&
    value.top_play_count >= 0 &&
    isNullableNumber(value.average_pp) &&
    isNullableNumber(value.average_accuracy) &&
    isNullableNumber(value.average_star_rating) &&
    isNullableNumber(value.average_approach_rate) &&
    isNullableNumber(value.average_bpm) &&
    Array.isArray(value.exact_mod_combinations) &&
    value.exact_mod_combinations.every(isModCombinationCount) &&
    Array.isArray(value.individual_mods) &&
    value.individual_mods.every(isIndividualModCount)
  );
}

interface PlayerAnalysisProps {
  analysis: PlayerAnalysisResponse;
  recommendationProfile: TargetRecommendationProfile | null;
  preferences: RecommendationPreferences | null;
}

function formatRange(first: number, third: number, precision: number): string {
  return `${first.toFixed(precision)}–${third.toFixed(precision)}`;
}

function formatPercentage(count: number, total: number): string {
  return total > 0 ? `${Math.round((count / total) * 100)}%` : "0%";
}

function PlayerAnalysis({ analysis, recommendationProfile, preferences }: PlayerAnalysisProps) {
  const primaryMods: ReactNode | null = recommendationProfile
    ? <ModBadges mods={recommendationProfile.primary_mods} />
    : null;
  const statistics: { label: string; value: ReactNode | null }[] = [
    { label: "Primary mods", value: primaryMods },
    { label: "Typical PP", value: recommendationProfile?.performance_points
      ? formatRange(recommendationProfile.performance_points.first_quartile, recommendationProfile.performance_points.third_quartile, 0)
      : null },
    { label: "Typical AR", value: preferences?.approach_rate
      ? formatRange(preferences.approach_rate.first_quartile, preferences.approach_rate.third_quartile, 1)
      : null },
    { label: "Typical BPM", value: preferences?.bpm
      ? formatRange(preferences.bpm.first_quartile, preferences.bpm.third_quartile, 0)
      : null },
  ].filter((statistic) => statistic.value !== null);

  return (
    <section className="analysis-panel" aria-labelledby="analysis-heading">
      <div className="analysis-heading-row">
        <h2 id="analysis-heading">
          <a href={`https://osu.ppy.sh/users/${analysis.user_id}`} target="_blank" rel="noopener noreferrer">
            {analysis.username}
          </a>
        </h2>
        <span className="user-id">#{analysis.user_id}</span>
      </div>

      <dl className="statistics-grid">
        {statistics.map((statistic) => (
          <div className="statistic" key={statistic.label}>
            <dt>{statistic.label}</dt>
            <dd>{statistic.value}</dd>
          </div>
        ))}
      </dl>

      <div className="mod-sections">
        <p className="playstyle-label">Playstyle</p>
        <section aria-labelledby="combinations-heading">
          <h3 id="combinations-heading">Exact combinations</h3>
          {analysis.exact_mod_combinations.length > 0 ? (
            <ul className="mod-count-list">
              {analysis.exact_mod_combinations.map((combination, index) => (
                <li key={`${combination.mods.join("-") || "NM"}-${index}`}>
                  <ModBadges mods={combination.mods} />
                  <strong>{formatPercentage(combination.count, analysis.top_play_count)}</strong>
                </li>
              ))}
            </ul>
          ) : (
            <p className="empty-message">No exact mod data available.</p>
          )}
        </section>

        <section aria-labelledby="individual-mods-heading">
          <h3 id="individual-mods-heading">Individual mods</h3>
          {analysis.individual_mods.length > 0 ? (
            <ul className="mod-count-list">
              {analysis.individual_mods.map((mod) => (
                <li key={mod.mod}>
                  <ModBadges mods={[mod.mod]} />
                  <strong>{formatPercentage(mod.count, analysis.top_play_count)}</strong>
                </li>
              ))}
            </ul>
          ) : (
            <p className="empty-message">No individual mod data available.</p>
          )}
        </section>
      </div>
    </section>
  );
}

export default PlayerAnalysis;
