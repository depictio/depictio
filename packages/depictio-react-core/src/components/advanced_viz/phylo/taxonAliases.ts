/**
 * Legacy phylum names mapped to the names current taxonomies use.
 *
 * Tip metadata often carries SILVA-era names (Proteobacteria, Bacteroidetes,
 * Crenarchaeota...) while a dashboard pins colours under the GTDB / LPSN names
 * (Pseudomonadota, Bacteroidota, Thermoproteota...). The two name the same
 * phylum, so a pin for one must colour the other.
 *
 * Source: the 2021 validation of phylum names under the ICNP, Oren & Garrity,
 * IJSEM 71:005056 (https://doi.org/10.1099/ijsem.0.005056).
 *
 * Used ONLY to find a pinned colour: labels always stay as the tree wrote them.
 * GTDB's suffixed groups (Firmicutes_A, ...) are deliberately not mapped: they
 * are separate phyla there, not spellings of one.
 */
const LEGACY_TO_CURRENT: Readonly<Record<string, string>> = {
  Proteobacteria: 'Pseudomonadota',
  Bacteroidetes: 'Bacteroidota',
  Actinobacteria: 'Actinomycetota',
  Actinobacteriota: 'Actinomycetota',
  Firmicutes: 'Bacillota',
  Chloroflexi: 'Chloroflexota',
  Acidobacteria: 'Acidobacteriota',
  Verrucomicrobia: 'Verrucomicrobiota',
  Planctomycetes: 'Planctomycetota',
  Cyanobacteria: 'Cyanobacteriota',
  Crenarchaeota: 'Thermoproteota',
  Euryarchaeota: 'Methanobacteriota',
  Thaumarchaeota: 'Nitrososphaerota',
  Spirochaetes: 'Spirochaetota',
  Nitrospirae: 'Nitrospirota',
  Gemmatimonadetes: 'Gemmatimonadota',
  Fusobacteria: 'Fusobacteriota',
  'Deinococcus-Thermus': 'Deinococcota',
  Tenericutes: 'Mycoplasmatota',
  Chlamydiae: 'Chlamydiota',
  Armatimonadetes: 'Armatimonadota',
  Elusimicrobia: 'Elusimicrobiota',
  Thermotogae: 'Thermotogota',
  Aquificae: 'Aquificota',
  Synergistetes: 'Synergistota',
  Fibrobacteres: 'Fibrobacterota',
  Lentisphaerae: 'Lentisphaerota',
  Deferribacteres: 'Deferribacterota',
  Dictyoglomi: 'Dictyoglomota',
  Chrysiogenetes: 'Chrysiogenota',
  Kiritimatiellaeota: 'Kiritimatiellota',
  Calditrichaeota: 'Calditrichota',
};

const CANONICAL: ReadonlyMap<string, string> = new Map(
  Object.entries(LEGACY_TO_CURRENT).map(([legacy, current]) => [
    legacy.toLowerCase(),
    current.toLowerCase(),
  ]),
);

/**
 * The key two spellings of one phylum share: the current name, lowercased.
 * A name the table does not know is its own key (still case-insensitive).
 */
export function canonicalTaxon(name: string): string {
  const key = name.trim().toLowerCase();
  return CANONICAL.get(key) ?? key;
}

/**
 * The colour pinned for `value`, under its own name or, failing that, under an
 * alias of it (legacy for current, or current for legacy). Undefined when
 * neither is pinned.
 */
export function pinnedColourFor(
  value: string,
  pins: Readonly<Record<string, string>> | null | undefined,
): string | undefined {
  if (!pins) return undefined;
  const own = pins[value];
  if (own) return own;
  const key = canonicalTaxon(value);
  for (const [name, colour] of Object.entries(pins)) {
    if (colour && canonicalTaxon(name) === key) return colour;
  }
  return undefined;
}
