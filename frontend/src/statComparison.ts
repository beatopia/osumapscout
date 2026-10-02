export type ComparisonCategory =
  | "typical"
  | "outside"
  | "unusually-high"
  | "unusually-low"
  | "neutral";

export interface PreferenceBounds {
  first_quartile: number;
  median: number;
  third_quartile: number;
}

export function compareToPreference(
  value: number | null,
  bounds: PreferenceBounds | null,
): ComparisonCategory {
  if (value === null || bounds === null) {
    return "neutral";
  }
  const width = bounds.third_quartile - bounds.first_quartile;
  if (width <= 0) {
    return "neutral";
  }
  if (value >= bounds.first_quartile && value <= bounds.third_quartile) {
    return "typical";
  }
  if (value > bounds.third_quartile + 1.5 * width) {
    return "unusually-high";
  }
  if (value < bounds.first_quartile - 1.5 * width) {
    return "unusually-low";
  }
  return "outside";
}

export const comparisonLabels: Record<ComparisonCategory, string> = {
  typical: "Within your usual range",
  outside: "Outside your usual range",
  "unusually-high": "Higher than what you usually play",
  "unusually-low": "Lower than what you usually play",
  neutral: "Comparison unavailable",
};
