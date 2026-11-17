// Detection heuristics for "extended" table categories — table data collections
// whose column shape suggests a specialized Pydantic subclass on the backend.
//
// Today: only coordinates (DCTableCoordinatesConfig — lat_column + lon_column).
// Used to suggest the marking on a table's page and to pre-fill the
// "Map coordinates" window; never applied without the user confirming it.

export type CoordinatesGuess = { latColumn: string; lonColumn: string } | null;

const LAT_PATTERNS = [/^lat$/i, /^latitude$/i];
const LON_PATTERNS = [/^lon$/i, /^lng$/i, /^long$/i, /^longitude$/i];

export function detectCoordinatesColumns(columns: string[]): CoordinatesGuess {
  const lat = columns.find((c) => LAT_PATTERNS.some((re) => re.test(c.trim())));
  const lon = columns.find((c) => LON_PATTERNS.some((re) => re.test(c.trim())));
  if (!lat || !lon || lat === lon) return null;
  return { latColumn: lat, lonColumn: lon };
}
