/**
 * What a card's number is, in words: "Median shannon", "Distinct ID values".
 * The card's title names the figure; this says how it was computed, for the
 * hover on the title (an aggregation in brackets, "(Median)", said neither).
 */
const PHRASES: Record<string, (column: string) => string> = {
  count: () => 'Number of rows',
  nunique: (c) => `Number of distinct ${c} values`,
  sum: (c) => `Sum of ${c}`,
  average: (c) => `Mean ${c}`,
  mean: (c) => `Mean ${c}`,
  median: (c) => `Median ${c}`,
  min: (c) => `Lowest ${c}`,
  max: (c) => `Highest ${c}`,
  range: (c) => `Range of ${c} (highest − lowest)`,
  variance: (c) => `Variance of ${c}`,
  std_dev: (c) => `Standard deviation of ${c}`,
  percentile: (c) => `Percentile of ${c}`,
  q1: (c) => `First quartile of ${c}`,
  q3: (c) => `Third quartile of ${c}`,
  skewness: (c) => `Skewness of ${c}`,
  kurtosis: (c) => `Kurtosis of ${c}`,
  mode: (c) => `Most frequent ${c}`,
};

export function describeAggregation(
  aggregation: string | null | undefined,
  column: string | null | undefined,
): string | null {
  if (!aggregation) return null;
  const col = column?.trim() || 'value';
  const phrase = PHRASES[aggregation];
  if (phrase) return phrase(col);
  return `${aggregation.charAt(0).toUpperCase()}${aggregation.slice(1).replace(/_/g, ' ')} of ${col}`;
}
