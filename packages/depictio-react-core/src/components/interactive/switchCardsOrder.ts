/**
 * The order a card switch reads in: the options the YAML declares, in the order
 * it declares them (SILVA before PR2), then any other value the column holds.
 * Alphabetical order would put PR2 first, and the first card is the one a reader
 * expects to be the default.
 */
export function orderByDeclared(values: readonly string[], declared: readonly string[]): string[] {
  const rank = (v: string) => {
    const i = declared.indexOf(v);
    return i === -1 ? declared.length : i;
  };
  // `sort` is stable, so values the YAML does not name keep their incoming order.
  return [...values].sort((a, b) => rank(a) - rank(b));
}
