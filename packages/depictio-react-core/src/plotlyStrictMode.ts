/**
 * Lets react-plotly.js survive React 18 StrictMode's unmount/remount.
 *
 * The component records the Plotly event handlers it attached in
 * `this.handlers` and never clears that record. StrictMode (dev only) unmounts
 * and remounts every component once: the unmount purges the plot, which drops
 * its listeners, and the remount's `syncEventHandlers` finds the same handler
 * functions already recorded, so it attaches nothing. A renderer that does not
 * re-render afterwards (a memoised one, such as the Manhattan) then never hears
 * `plotly_selected` or `plotly_click`, and a lasso draws but selects nothing.
 * Forgetting the record on unmount makes the remount attach them again.
 */
import Plot from 'react-plotly.js';

interface PlotInstance {
  handlers?: Record<string, unknown>;
}

type Unmount = ((this: PlotInstance) => void) & { depictioResetsHandlers?: true };

const proto = (Plot as unknown as { prototype: { componentWillUnmount?: Unmount } }).prototype;
const unmount = proto.componentWillUnmount;

// Guarded so a hot reload of this module does not wrap the method twice.
if (unmount && !unmount.depictioResetsHandlers) {
  const resetting: Unmount = function (this: PlotInstance) {
    unmount.call(this);
    this.handlers = {};
  };
  resetting.depictioResetsHandlers = true;
  proto.componentWillUnmount = resetting;
}
