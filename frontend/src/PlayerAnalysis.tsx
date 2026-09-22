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

function formatNumber(value: number | null, decimals = 2): string {
  return value === null ? "Unavailable" : value.toFixed(decimals);
}

interface PlayerAnalysisProps {
  analysis: PlayerAnalysisResponse;
}

function PlayerAnalysis({ analysis }: PlayerAnalysisProps) {
  const statistics = [
    { label: "Top plays", value: analysis.top_play_count.toString() },
    { label: "Average PP", value: formatNumber(analysis.average_pp) },
    {
      label: "Average accuracy",
      value:
        analysis.average_accuracy === null
          ? "Unavailable"
          : `${(analysis.average_accuracy * 100).toFixed(2)}%`,
    },
    {
      label: "Average stars",
      value: formatNumber(analysis.average_star_rating),
    },
    { label: "Average AR", value: formatNumber(analysis.average_approach_rate) },
    { label: "Average BPM", value: formatNumber(analysis.average_bpm, 1) },
  ];

  return (
    <section className="analysis-panel" aria-labelledby="analysis-heading">
      <div className="analysis-heading-row">
        <div>
          <p className="eyebrow">Persisted analysis</p>
          <h2 id="analysis-heading">{analysis.username}</h2>
        </div>
        <span className="user-id">User ID {analysis.user_id}</span>
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
        <section aria-labelledby="combinations-heading">
          <h3 id="combinations-heading">Exact mod combinations</h3>
          <p className="section-description">
            Each row counts a complete combination used on a top play.
          </p>
          {analysis.exact_mod_combinations.length > 0 ? (
            <ul className="mod-count-list">
              {analysis.exact_mod_combinations.map((combination, index) => (
                <li key={`${combination.mods.join("-") || "NM"}-${index}`}>
                  <span>{combination.mods.length > 0 ? combination.mods.join(" ") : "NM"}</span>
                  <strong>{combination.count}</strong>
                </li>
              ))}
            </ul>
          ) : (
            <p className="empty-message">No exact mod data available.</p>
          )}
        </section>

        <section aria-labelledby="individual-mods-heading">
          <h3 id="individual-mods-heading">Individual mod usage</h3>
          <p className="section-description">
            Each acronym is counted separately when it appears in a combination.
          </p>
          {analysis.individual_mods.length > 0 ? (
            <ul className="mod-count-list">
              {analysis.individual_mods.map((mod) => (
                <li key={mod.mod}>
                  <span>{mod.mod}</span>
                  <strong>{mod.count}</strong>
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
