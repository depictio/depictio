/** The calm field behind a dashboard (or tab) that has no screenshot yet: a
 *  soft tint of its own icon colour fading to a fainter one, mixed into the
 *  page body so it reads the same on light and dark. `color` is a Mantine
 *  colour name, or a raw CSS colour for a custom one. */
export function placeholderBackground(color: string): string {
  const c = /^[a-z]+$/i.test(color) ? `var(--mantine-color-${color}-6)` : color;
  const tint = (pct: number) => `color-mix(in srgb, ${c} ${pct}%, var(--mantine-color-body))`;
  return `linear-gradient(135deg, ${tint(20)} 0%, ${tint(7)} 100%)`;
}
