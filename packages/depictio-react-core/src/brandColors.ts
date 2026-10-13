/**
 * depictio's brand palette.
 *
 * Duplicated from `depictio/dash/colors.py` historically; it now lives here so
 * the shared components can use it without importing out of the viewer app.
 * `depictio/viewer/src/profile/colors.ts` re-exports this.
 */
export const brandColors = {
  purple: '#9966CC',
  violet: '#7A5DC7',
  blue: '#6495ED',
  teal: '#45B8AC',
  green: '#8BC34A',
  yellow: '#F9CB40',
  orange: '#F68B33',
  pink: '#E6779F',
  red: '#E53935',
} as const;
