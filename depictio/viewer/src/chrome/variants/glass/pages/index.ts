/**
 * Glass for the page apps (management pages and the sign-in page): the
 * Glass dashboard chrome's language, applied where there is no
 * dashboard. Everything here renders only when the active chrome style is
 * `glass`; with Classic (`base`) the pages keep their own shells.
 */
export { useGlassPages, usePageMark, GLASS_ID } from './useGlassPages';
export { default as GlassPage, GlassKey, HomeMark, STROKE } from './GlassPage';
export type { Crumb, GlassPageProps } from './GlassPage';
export { default as GlassTray } from './GlassTray';
