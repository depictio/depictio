/**
 * Compact re-exports so App.tsx can `import { Header, Sidebar, ... } from './chrome'`.
 */
export { default as Header } from './Header';
export { default as Sidebar } from './Sidebar';
export { default as AppSidebar } from './AppSidebar';
export type { SidebarSection } from './AppSidebar';
export { default as ThemeToggle } from './ThemeToggle';
export { default as ServerStatusBadge } from './ServerStatusBadge';
export { default as ProfileBadge } from './ProfileBadge';
export { default as AuthModeBadge } from './AuthModeBadge';
export { default as PoweredBy } from './PoweredBy';
export { default as SettingsDrawer } from './SettingsDrawer';
export { default as TabModal } from './TabModal';
export type { TabModalSubmitPayload } from './TabModal';
