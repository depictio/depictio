import { describe, expect, it } from 'vitest';

import {
  createOnceFlag,
  isZoomWheel,
  plotlyCanZoom,
  visibleCenter,
  wheelVerdict,
  ZOOM_HINT_STORAGE_KEY,
  zoomHintDelayMs,
  zoomHintText,
  type PlotlyZoomProbe,
  type StorageLike,
} from './zoomGate';

describe('isZoomWheel', () => {
  it('zooms on Ctrl, on Cmd, and on a trackpad pinch (a wheel with ctrlKey set)', () => {
    expect(isZoomWheel({ ctrlKey: true })).toBe(true);
    expect(isZoomWheel({ metaKey: true })).toBe(true);
    expect(isZoomWheel({ ctrlKey: true, metaKey: true })).toBe(true);
  });

  it('leaves a plain wheel, and a shift or alt wheel, to scrolling', () => {
    expect(isZoomWheel({})).toBe(false);
    expect(isZoomWheel({ ctrlKey: false, metaKey: false })).toBe(false);
  });
});

describe('wheelVerdict', () => {
  it('lets a zoom wheel through, wherever it lands', () => {
    expect(wheelVerdict({ ctrlKey: true }, false)).toBe('zoom');
    expect(wheelVerdict({ metaKey: true }, true)).toBe('zoom');
  });

  it('keeps a plain wheel from the library, except over a part that scrolls itself', () => {
    expect(wheelVerdict({}, false)).toBe('block');
    expect(wheelVerdict({}, true)).toBe('pass');
  });
});

describe('zoomHintText', () => {
  const mac = { platform: 'MacIntel', userAgent: 'Mozilla/5.0 (Macintosh)' };
  const win = { platform: 'Win32', userAgent: 'Mozilla/5.0 (Windows NT 10.0)' };
  const linux = { platform: 'Linux x86_64', userAgent: 'Mozilla/5.0 (X11; Linux x86_64)' };

  it('names the Command key on macOS and Ctrl elsewhere', () => {
    expect(zoomHintText(false, mac)).toBe('⌘ + scroll to zoom');
    expect(zoomHintText(false, win)).toBe('Ctrl + scroll to zoom');
    expect(zoomHintText(false, linux)).toBe('Ctrl + scroll to zoom');
  });

  it('asks for a pinch on a touch screen, whatever the platform', () => {
    expect(zoomHintText(true, mac)).toBe('Pinch to zoom');
    expect(zoomHintText(true, win)).toBe('Pinch to zoom');
  });
});

describe('zoomHintDelayMs', () => {
  it('waits out a pointer sweeping past, but not a finger that landed', () => {
    expect(zoomHintDelayMs(false)).toBeGreaterThan(0);
    expect(zoomHintDelayMs(true)).toBe(0);
  });
});

describe('visibleCenter', () => {
  const viewport = { width: 1000, height: 800 };

  it('centres on a figure that is fully in view', () => {
    expect(visibleCenter({ left: 100, top: 200, right: 500, bottom: 600 }, viewport)).toEqual({
      x: 300,
      y: 400,
    });
  });

  it('centres on the visible part of a figure that runs off the viewport', () => {
    // 1200 px tall, scrolled so only its lower 300 px (500..800) show.
    expect(visibleCenter({ left: 0, top: -700, right: 400, bottom: 800 }, viewport)).toEqual({
      x: 200,
      y: 400,
    });
    expect(visibleCenter({ left: 900, top: 100, right: 1500, bottom: 300 }, viewport)).toEqual({
      x: 950,
      y: 200,
    });
  });

  it('gives nothing for a figure that is out of view', () => {
    expect(visibleCenter({ left: 0, top: 900, right: 400, bottom: 1200 }, viewport)).toBeNull();
    expect(visibleCenter({ left: 0, top: -300, right: 400, bottom: 0 }, viewport)).toBeNull();
  });
});

/** An in-memory `Storage` stand-in, so two flags can share one "browser". */
function memoryStorage(): StorageLike & { data: Map<string, string> } {
  const data = new Map<string, string>();
  return {
    data,
    getItem: (k) => data.get(k) ?? null,
    setItem: (k, v) => void data.set(k, v),
  };
}

describe('createOnceFlag', () => {
  it('is unset until marked, then set', () => {
    const flag = createOnceFlag(ZOOM_HINT_STORAGE_KEY, () => memoryStorage());
    expect(flag.seen()).toBe(false);
    flag.mark();
    expect(flag.seen()).toBe(true);
  });

  it('is kept in storage, so a later page load sees it', () => {
    const storage = memoryStorage();
    createOnceFlag(ZOOM_HINT_STORAGE_KEY, () => storage).mark();
    expect(storage.data.get(ZOOM_HINT_STORAGE_KEY)).toBe('1');
    expect(createOnceFlag(ZOOM_HINT_STORAGE_KEY, () => storage).seen()).toBe(true);
    expect(createOnceFlag('another.key', () => storage).seen()).toBe(false);
  });

  it('still holds for the page when storage throws on read and write', () => {
    const broken: StorageLike = {
      getItem: () => {
        throw new Error('SecurityError');
      },
      setItem: () => {
        throw new Error('QuotaExceededError');
      },
    };
    const flag = createOnceFlag(ZOOM_HINT_STORAGE_KEY, () => broken);
    expect(flag.seen()).toBe(false);
    expect(() => flag.mark()).not.toThrow();
    expect(flag.seen()).toBe(true);
  });

  it('survives storage that cannot even be reached', () => {
    const throwing = () => {
      throw new Error('access denied');
    };
    const flag = createOnceFlag(ZOOM_HINT_STORAGE_KEY, throwing);
    expect(flag.seen()).toBe(false);
    expect(() => flag.mark()).not.toThrow();
    expect(flag.seen()).toBe(true);

    const none = createOnceFlag(ZOOM_HINT_STORAGE_KEY, () => null);
    expect(none.seen()).toBe(false);
    none.mark();
    expect(none.seen()).toBe(true);
  });

  it('stops reading storage once it has seen the flag', () => {
    let reads = 0;
    const storage: StorageLike = {
      getItem: () => {
        reads += 1;
        return '1';
      },
      setItem: () => {},
    };
    const flag = createOnceFlag(ZOOM_HINT_STORAGE_KEY, () => storage);
    expect(flag.seen()).toBe(true);
    expect(flag.seen()).toBe(true);
    expect(reads).toBe(1);
  });
});

describe('plotlyCanZoom', () => {
  /** A drawn figure that has the given subplot types and axes. */
  const drawn = (
    types: string[],
    scrollZoom: unknown,
    axes: Record<string, { fixedrange?: boolean }> = { xaxis: {}, yaxis: {} },
  ): PlotlyZoomProbe => ({
    _fullLayout: { _has: (t: string) => types.includes(t), ...axes },
    _context: { scrollZoom },
  });

  it('zooms a cartesian figure on a wheel once scrollZoom is on and an axis is free', () => {
    expect(plotlyCanZoom(drawn(['cartesian'], true), false)).toBe(true);
    expect(plotlyCanZoom(drawn(['cartesian'], 'cartesian'), false)).toBe(true);
    expect(plotlyCanZoom(drawn(['cartesian'], false), false)).toBe(false);
    // Plotly's own default leaves cartesian out.
    expect(plotlyCanZoom(drawn(['cartesian'], 'gl3d+geo+map'), false)).toBe(false);
  });

  it('does not offer a zoom on a figure whose axes are all fixed', () => {
    const fixed = drawn(['cartesian'], true, {
      xaxis: { fixedrange: true },
      yaxis: { fixedrange: true },
    });
    expect(plotlyCanZoom(fixed, false)).toBe(false);
    const oneFree = drawn(['cartesian'], true, {
      xaxis: { fixedrange: true },
      yaxis: { fixedrange: false },
      xaxis2: { fixedrange: true },
    });
    expect(plotlyCanZoom(oneFree, false)).toBe(true);
  });

  it('does not offer a zoom on figures with no spatial subplot (pie, sankey, parcoords)', () => {
    expect(plotlyCanZoom(drawn(['pie'], true, {}), false)).toBe(false);
    expect(plotlyCanZoom(drawn(['sankey'], true, {}), true)).toBe(false);
  });

  it('zooms 3D, geo and map subplots on a wheel when scrollZoom names them', () => {
    expect(plotlyCanZoom(drawn(['gl3d'], 'gl3d+geo+map', {}), false)).toBe(true);
    expect(plotlyCanZoom(drawn(['map'], true, {}), false)).toBe(true);
    expect(plotlyCanZoom(drawn(['geo'], false, {}), false)).toBe(false);
  });

  it('offers a pinch only where the library has one', () => {
    expect(plotlyCanZoom(drawn(['cartesian'], true), true)).toBe(false);
    expect(plotlyCanZoom(drawn(['gl3d'], true, {}), true)).toBe(true);
    expect(plotlyCanZoom(drawn(['map'], true, {}), true)).toBe(true);
    expect(plotlyCanZoom(drawn(['geo'], true, {}), true)).toBe(true);
  });

  it('stays quiet for a static or undrawn figure', () => {
    expect(
      plotlyCanZoom({ ...drawn(['cartesian'], true), _context: { scrollZoom: true, staticPlot: true } }, false),
    ).toBe(false);
    expect(plotlyCanZoom({}, false)).toBe(false);
    expect(plotlyCanZoom({ _context: { scrollZoom: true } }, false)).toBe(false);
    expect(plotlyCanZoom({ _fullLayout: {}, _context: { scrollZoom: true } }, false)).toBe(false);
  });
});
