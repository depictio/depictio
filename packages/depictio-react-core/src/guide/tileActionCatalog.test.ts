import { describe, expect, it } from 'vitest';

import { EDIT_MENU_STYLE, TILE_ACTION_STYLE } from '../components/chrome/actionStyles';
import { actionsFor } from '../components/chrome/chromeActions';
import {
  editActionsFor,
  GUIDE_TILE_TYPES,
  ownControlsFor,
  rowActionsFor,
} from './tileActionCatalog';

describe('rowActionsFor', () => {
  it("lists every action the chrome draws for the type, in the chrome's order", () => {
    for (const type of GUIDE_TILE_TYPES) {
      const keys = rowActionsFor(type).map((a) => a.key);
      // Reset only exists where a selection (or a filter value) can be made.
      const chrome = actionsFor(type).filter((a) => a !== 'reset' || keys.includes('reset'));
      const inRow = keys.filter((k) => (chrome as string[]).includes(k));
      expect(inRow, type).toEqual(chrome);
    }
  });

  it('takes icon and colour from the shared styles', () => {
    for (const type of GUIDE_TILE_TYPES) {
      for (const a of rowActionsFor(type)) {
        expect(a.icon).toBe(TILE_ACTION_STYLE[a.key].icon);
        expect(a.color).toBe((TILE_ACTION_STYLE[a.key] as { color?: string }).color);
      }
    }
  });

  it('gives each type the actions its renderer adds', () => {
    expect(rowActionsFor('table').map((a) => a.key)).toEqual([
      'group',
      'inspect',
      'catalog',
      'description',
      'metadata',
      'fullscreen',
      'download',
      'reset',
      'loadAll',
    ]);
    expect(rowActionsFor('card').map((a) => a.key)).toEqual([
      'inspect',
      'catalog',
      'description',
      'metadata',
    ]);
    const viz = rowActionsFor('advanced_viz').map((a) => a.key);
    expect(viz).not.toContain('description');
    expect(viz).toEqual(expect.arrayContaining(['settings', 'data', 'source']));
    expect(rowActionsFor('map').map((a) => a.key)).toEqual(
      expect.arrayContaining(['settings', 'data', 'reset']),
    );
  });

  it('says what each type draws inside the tile', () => {
    for (const type of GUIDE_TILE_TYPES) expect(ownControlsFor(type).length).toBeGreaterThan(0);
  });
});

describe('editActionsFor', () => {
  it('lists the grip, the corner and the whole menu without a type', () => {
    expect(editActionsFor().map((a) => a.key)).toEqual([
      'drag',
      'resize',
      'edit',
      'duplicate',
      'move-section',
      'copy-tab',
      'highlight',
      'font-size',
      'delete',
    ]);
    expect(editActionsFor().find((a) => a.key === 'delete')?.color).toBe(
      EDIT_MENU_STYLE.delete.color,
    );
  });

  it("keeps only what a type's menu offers", () => {
    const table = editActionsFor('table').map((a) => a.key);
    expect(table).not.toContain('duplicate');
    expect(table).not.toContain('font-size');
    expect(table).not.toContain('highlight');
    expect(editActionsFor('figure').map((a) => a.key)).toContain('font-size');
    expect(
      editActionsFor('figure', { hasSections: false, hasOtherTabs: false }).map((a) => a.key),
    ).toEqual(['drag', 'resize', 'edit', 'duplicate', 'font-size', 'delete']);
  });
});
