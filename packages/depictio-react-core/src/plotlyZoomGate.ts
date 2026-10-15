/**
 * Puts every react-plotly.js figure under the zoom rule (components/zoomGate.ts):
 * a plain wheel scrolls the page, Ctrl / Cmd + wheel zooms.
 *
 * Plotly zooms a 3D, geo or map subplot on a plain wheel by default and a
 * cartesian one not at all, so two things change for all figures at once,
 * instead of in the config of each of the ~50 call sites:
 *   - `scrollZoom` defaults to on (`setPlotConfig`), so Ctrl / Cmd + wheel
 *     zooms a cartesian figure too. A config that sets it still wins.
 *   - each `Plot` mounts the gate on its graph div, which keeps a plain wheel
 *     from Plotly's wheel handlers (drag layer, WebGL canvas, map canvas).
 *
 * Like plotlyStrictMode, this patches the `Plot` prototype and must be
 * imported before any Plot mounts.
 */
import Plotly from 'plotly.js';
import Plot from 'react-plotly.js';

import { attachZoomGate } from './components/zoomGateDom';
import { plotlyCanZoom, type PlotlyZoomProbe } from './components/zoomGate';

interface PlotInstance {
  el?: HTMLElement | null;
  depictioZoomGateOff?: () => void;
}

type Method = ((this: PlotInstance) => void) & { depictioZoomGate?: true };

Plotly.setPlotConfig({ scrollZoom: true });

const proto = (Plot as unknown as {
  prototype: { componentDidMount?: Method; componentWillUnmount?: Method };
}).prototype;

// Guarded so a hot reload of this module does not wrap the methods twice.
const mount = proto.componentDidMount;
if (mount && !mount.depictioZoomGate) {
  const gated: Method = function (this: PlotInstance) {
    mount.call(this);
    const gd = this.el;
    if (!gd) return;
    this.depictioZoomGateOff?.();
    this.depictioZoomGateOff = attachZoomGate(gd, {
      // A long legend scrolls on a plain wheel, and hands the rest to the page.
      passThrough: '.legend',
      canZoom: (touch) => plotlyCanZoom(gd as unknown as PlotlyZoomProbe, touch),
    });
  };
  gated.depictioZoomGate = true;
  proto.componentDidMount = gated;
}

const unmount = proto.componentWillUnmount;
if (unmount && !unmount.depictioZoomGate) {
  const released: Method = function (this: PlotInstance) {
    this.depictioZoomGateOff?.();
    this.depictioZoomGateOff = undefined;
    unmount.call(this);
  };
  released.depictioZoomGate = true;
  proto.componentWillUnmount = released;
}
