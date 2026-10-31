import { describe, expect, it } from 'vitest';
import { action, makeAutoObservable } from 'mobx';

import { type FeatureWidgetLike, watchFeatureWidgets } from './featureWidgetWatch';

function fakeSession() {
  const session = makeAutoObservable({
    visibleWidget: undefined as FeatureWidgetLike | undefined,
    hideAllWidgets() {
      session.visibleWidget = undefined;
    },
  });
  const open = action((w: FeatureWidgetLike) => {
    session.visibleWidget = w;
  });
  return { session, open };
}

const clicked = { type: 'BaseFeatureWidget', track: { configuration: 'cell-1' } };

describe('watchFeatureWidgets', () => {
  it('hands the widget to the click handler before the panel hides it', () => {
    const { session, open } = fakeSession();
    const seen: FeatureWidgetLike[] = [];
    const stop = watchFeatureWidgets(session, {
      onFeatureWidget: (w) => seen.push(w),
      show: () => true,
    });
    open(clicked);
    expect(seen).toEqual([clicked]);
    expect(session.visibleWidget).toBeUndefined();
    stop();
  });

  it('leaves the widget open when the panel does not take it', () => {
    const { session, open } = fakeSession();
    const stop = watchFeatureWidgets(session, { show: () => false });
    open(clicked);
    expect(session.visibleWidget).toEqual(clicked);
    stop();
  });

  it('ignores widgets that are not feature details', () => {
    const { session, open } = fakeSession();
    const seen: FeatureWidgetLike[] = [];
    const stop = watchFeatureWidgets(session, {
      onFeatureWidget: (w) => seen.push(w),
      show: () => true,
    });
    const config = { type: 'ConfigurationEditorWidget' };
    open(config);
    expect(seen).toEqual([]);
    expect(session.visibleWidget).toEqual(config);
    stop();
  });

  it('still shows the details when the click handler throws', () => {
    const { session, open } = fakeSession();
    let shown = 0;
    const stop = watchFeatureWidgets(session, {
      onFeatureWidget: () => {
        throw new Error('boom');
      },
      show: () => {
        shown += 1;
        return true;
      },
    });
    open(clicked);
    expect(shown).toBe(1);
    stop();
  });
});
