/**
 * What a Basic and an Advanced project are, said once: the cards of the
 * create dialog and the badge of a project's page read the same words.
 */
export type ProjectKind = 'basic' | 'advanced';

export interface ProjectKindFact {
  icon: string;
  label: string;
  value: string;
}

export interface ProjectKindInfo {
  title: string;
  /** The short tag under the card. */
  tag: string;
  icon: string;
  /** One sentence: what the project is. */
  summary: string;
  facts: ProjectKindFact[];
}

export const PROJECT_KINDS: Record<ProjectKind, ProjectKindInfo> = {
  basic: {
    title: 'Basic Project',
    tag: 'Upload in the UI',
    icon: 'mdi:view-dashboard-outline',
    summary: 'Upload files in the browser and explore them. No pipeline, no folder to point at.',
    facts: [
      { icon: 'mdi:upload-outline', label: 'Data', value: 'Files you upload in the browser' },
      { icon: 'mdi:table', label: 'Structure', value: 'Data collections only, no workflow' },
      {
        icon: 'mdi:flag-outline',
        label: 'You start by',
        value: 'Naming the project, then adding collections from its page',
      },
      { icon: 'mdi:star-outline', label: 'Best for', value: 'One dataset, or a quick look' },
    ],
  },
  advanced: {
    title: 'Advanced Project',
    tag: 'From a folder',
    icon: 'mdi:sitemap',
    summary:
      'Read the output of a pipeline run, or any folder, where it is. Collections are grouped under workflows.',
    facts: [
      { icon: 'mdi:folder-outline', label: 'Data', value: 'A folder or an s3:// location that Depictio reads' },
      { icon: 'mdi:sitemap-outline', label: 'Structure', value: 'Workflows, each with its data collections' },
      {
        icon: 'mdi:flag-outline',
        label: 'You start by',
        value: 'Picking the folder: use the recognised template, edit it, or define the collections yourself',
      },
      {
        icon: 'mdi:star-outline',
        label: 'Best for',
        value: 'Pipeline outputs, and projects with many samples or runs',
      },
    ],
  },
};

/** Badge props of a project kind: both stay in the teal family, Basic as a
 *  light tint and Advanced as a teal-to-cyan gradient, so they read as two
 *  levels of one thing and tell apart at a glance. */
export function kindBadgeProps(kind: ProjectKind) {
  return kind === 'advanced'
    ? ({ variant: 'gradient', gradient: { from: 'teal.7', to: 'cyan.5', deg: 90 } } as const)
    : ({ variant: 'light', color: 'teal' } as const);
}

/** The icon colour of a kind's card: a lighter teal for Basic, a deeper one for Advanced. */
export const KIND_ACCENT: Record<ProjectKind, string> = {
  basic: 'var(--mantine-color-teal-5)',
  advanced: 'var(--mantine-color-teal-8)',
};
