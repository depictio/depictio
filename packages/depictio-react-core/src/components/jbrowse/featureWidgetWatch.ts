import { reaction } from 'mobx';

import { isFeatureWidgetType } from './featureDetailsModel';

export interface FeatureWidgetLike {
  type?: string;
  featureData?: unknown;
  unformattedFeatureData?: unknown;
  descriptions?: unknown;
  track?: { configuration?: unknown } | null;
}

export interface FeatureWidgetSession {
  visibleWidget?: FeatureWidgetLike;
  hideAllWidgets: () => void;
}

/**
 * The one watcher of the feature widgets JBrowse opens on a click.
 *
 * Every feature widget is handed to `onFeatureWidget` first (click-to-filter
 * reads its track there), then to `show`, which returns true when it took the
 * widget over (Depictio's panel): only then is the widget hidden. A second
 * reaction on `session.visibleWidget` would see `undefined` whenever this one
 * ran first and hid it, which is how click-to-filter once stopped filtering.
 */
export function watchFeatureWidgets(
  session: FeatureWidgetSession,
  handlers: {
    onFeatureWidget?: (widget: FeatureWidgetLike) => void;
    show: (widget: FeatureWidgetLike) => boolean;
  },
): () => void {
  return reaction(
    () => session.visibleWidget,
    (widget) => {
      if (!widget || !isFeatureWidgetType(widget.type)) return;
      try {
        handlers.onFeatureWidget?.(widget);
      } catch (err) {
        console.warn('jbrowse: feature click handler failed', err);
      }
      if (handlers.show(widget)) session.hideAllWidgets();
    },
  );
}
