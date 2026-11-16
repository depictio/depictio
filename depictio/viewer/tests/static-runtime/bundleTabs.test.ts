/**
 * The bundle's tab list is what the left rail, the Paper rail and the tab
 * links of text tiles read. It used to carry only id, title, order, parent and
 * one merged icon, so a bundle's rail was flat (no `tab_group` sections), the
 * main pill showed the dashboard title instead of `main_tab_name`, and the
 * MultiQC tab lost its logo: a CHILD tab draws an image icon only from its
 * own `tab_icon`.
 *
 * Run like tests/projects (the viewer package has no vitest of its own):
 *   pnpm --filter depictio-react-core exec vitest run --root ../../depictio/viewer tests/static-runtime
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import type { BundleManifest, TabEntry } from 'depictio-static-core';
// The module itself, not the barrel: the barrel pulls Plotly, which needs a DOM.
import { groupTabs } from '../../../../packages/depictio-react-core/src/components/tabGroups';

import { summariesFromTabs } from '../../src/static-runtime/bundle';

const FIXTURE = join(
  __dirname,
  '../../../../packages/depictio-static-core/fixtures/manifest-tabs.json',
);
const manifest = JSON.parse(readFileSync(FIXTURE, 'utf-8')) as BundleManifest;

describe('summariesFromTabs', () => {
  const summaries = summariesFromTabs(manifest.tabs, manifest.project?.id ?? null);

  it('draws the same sections as the live rail', () => {
    const sections = groupTabs(summaries).map((s) => [
      s.group,
      s.tabs.map((t) => t.title),
    ]);
    expect(sections).toEqual([
      [null, ['Fixture dashboard']],
      ['Analysis', ['Distributions', 'Details']],
      ['Quality', ['MultiQC']],
    ]);
  });

  it('names the main tab by main_tab_name and makes it the family root', () => {
    const [main, ...children] = summaries;
    expect(main.main_tab_name).toBe('Overview');
    expect(main.parent_dashboard_id).toBeNull();
    expect(main.tab_group).toBeNull();
    for (const child of children) {
      expect(child.parent_dashboard_id).toBe(main.dashboard_id);
      expect(child.main_tab_name).toBeUndefined();
    }
  });

  it("keeps a child tab's own image icon (the MultiQC logo)", () => {
    const mqc = summaries.find((s) => s.title === 'MultiQC')!;
    expect(mqc.tab_icon).toBe('/assets/images/logos/multiqc_icon_color.svg');
    expect(summaries.find((s) => s.title === 'Distributions')!.subtitle).toBe(
      'How the measures spread',
    );
  });

  it('names the project every tab belongs to', () => {
    expect(new Set(summaries.map((s) => s.project_id))).toEqual(new Set([manifest.project!.id]));
  });

  it('reads the tab documents for manifests written before the fields', () => {
    // An older producer wrote only the merged icon; the documents carry the rest.
    const legacy: TabEntry[] = [
      {
        id: 'm',
        title: 'nf-core/ampliseq',
        tab_order: 0,
        is_main_tab: true,
        icon: 'mdi:compass-outline',
        icon_color: 'brandPrimary',
        doc: {
          main_tab_name: 'Overview',
          tab_icon: 'mdi:compass-outline',
          icon: '/assets/images/workflows/nf-core.png',
          show_guide: false,
          guide_intro: 'Start here.',
        },
      },
      {
        id: 'q',
        title: 'MultiQC',
        tab_order: 1,
        is_main_tab: false,
        icon: '/assets/images/logos/multiqc_icon_color.svg',
        icon_color: 'orange',
        doc: {
          tab_group: 'Data & QC',
          tab_icon: '/assets/images/logos/multiqc_icon_color.svg',
          tab_icon_color: 'orange',
          icon: '/assets/images/workflows/nf-core.png',
          icon_color: 'green',
        },
      },
    ];
    const [main, mqc] = summariesFromTabs(legacy);
    expect(main.main_tab_name).toBe('Overview');
    expect(main.tab_icon).toBe('mdi:compass-outline');
    expect(main.icon).toBe('/assets/images/workflows/nf-core.png');
    expect(main.show_guide).toBe(false);
    expect(main.guide_intro).toBe('Start here.');
    expect(mqc.tab_group).toBe('Data & QC');
    expect(mqc.tab_icon).toBe('/assets/images/logos/multiqc_icon_color.svg');
    expect(mqc.icon_color).toBe('green');
    expect(mqc.project_id).toBeUndefined();
  });

  it('treats a null entry field as unset, not as "look in the document"', () => {
    const [main] = summariesFromTabs([
      {
        id: 'm',
        title: 'T',
        tab_order: 0,
        is_main_tab: true,
        main_tab_name: null,
        tab_group: null,
        tab_icon: null,
        tab_icon_color: null,
        subtitle: null,
        doc: { main_tab_name: 'stale', tab_icon: 'mdi:stale' },
      },
    ]);
    expect(main.main_tab_name).toBeUndefined();
    expect(main.tab_icon).toBeUndefined();
  });

  it('is empty for a single-tab bundle', () => {
    expect(summariesFromTabs([])).toEqual([]);
  });
});
