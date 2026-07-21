/**
 * In-browser Python executor for the figure Code Mode, so a no-backend app can
 * still run Plotly-Express code. Pyodide (+ pandas/numpy/plotly) is lazily
 * loaded from the jsDelivr CDN on first Execute — nothing downloads until the
 * user opens Code Mode. Mirrors depictio's server contract (`code_executor.py`)
 * as closely as the browser allows: the user's code gets `df` (a pandas
 * DataFrame of the fixture — Polars isn't available in Pyodide) plus
 * `px`/`go`/`pd`/`np`, and must assign a Plotly figure to `fig`.
 *
 * This is an authoring aid; depictio's Python renderer remains authoritative.
 */
import type { ParsedFixture } from '../types';

export interface PlotlyFigure {
  data: Record<string, unknown>[];
  layout: Record<string, unknown>;
}
export interface RunResult {
  figure?: PlotlyFigure;
  error?: string;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Pyodide = any;

let pyodidePromise: Promise<Pyodide> | null = null;

/** True once the interpreter has finished its (one-time) warm-up. */
export function isPyodideReady(): boolean {
  return ready;
}
let ready = false;

/** Lazily load Pyodide + pandas/numpy + plotly. Memoized: the heavy download
 *  happens once per session, on first Execute. */
export async function getPyodide(): Promise<Pyodide> {
  if (!pyodidePromise) {
    pyodidePromise = (async () => {
      const mod = await import('pyodide');
      // Match the wheel CDN to the installed loader version so they never skew.
      const pyodide = await mod.loadPyodide({
        indexURL: `https://cdn.jsdelivr.net/pyodide/v${mod.version}/full/`,
      });
      await pyodide.loadPackage(['pandas', 'numpy', 'micropip']);
      const micropip = pyodide.pyimport('micropip');
      await micropip.install('plotly');
      ready = true;
      return pyodide;
    })().catch((e) => {
      // Don't leave a rejected promise memoized — a transient CDN failure would
      // otherwise brick Code Mode for the whole session. Clear so Execute retries.
      pyodidePromise = null;
      throw e;
    });
  }
  return pyodidePromise;
}

const PREAMBLE = `
import warnings
warnings.filterwarnings('ignore')  # silence pandas/plotly deprecation noise in the console
import json
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import numpy as np

df = pd.DataFrame(json.loads(__cs_records))
__cols = json.loads(__cs_columns)
if len(df.columns):
    df = df[[c for c in __cols if c in df.columns]]
for __c in json.loads(__cs_numeric):
    if __c in df.columns:
        df[__c] = pd.to_numeric(df[__c], errors='coerce')
for __c in json.loads(__cs_datetime):
    if __c in df.columns:
        df[__c] = pd.to_datetime(df[__c], errors='coerce')

__user_ns = {'df': df, 'px': px, 'go': go, 'pd': pd, 'np': np}
exec(__cs_code, __user_ns)
fig = __user_ns.get('fig')
if fig is None or not hasattr(fig, 'to_json'):
    raise ValueError("Your code must assign a Plotly figure to a variable named 'fig'.")
__cs_result = fig.to_json()
`;

/** Run the user's Code-Mode snippet against the fixture and return a Plotly
 *  {data, layout}. Never throws — Python errors come back in `error`. */
export async function runCodeToFigure(code: string, fixture: ParsedFixture): Promise<RunResult> {
  let pyodide: Pyodide;
  try {
    pyodide = await getPyodide();
  } catch (e) {
    return { error: `Failed to load the in-browser Python runtime: ${(e as Error).message}` };
  }

  const numeric = fixture.columns.filter((c) => c.dtype === 'Int64' || c.dtype === 'Float64').map((c) => c.name);
  const datetime = fixture.columns.filter((c) => c.dtype === 'Datetime').map((c) => c.name);

  pyodide.globals.set('__cs_records', JSON.stringify(fixture.rows));
  pyodide.globals.set('__cs_columns', JSON.stringify(fixture.columns.map((c) => c.name)));
  pyodide.globals.set('__cs_numeric', JSON.stringify(numeric));
  pyodide.globals.set('__cs_datetime', JSON.stringify(datetime));
  pyodide.globals.set('__cs_code', code);

  try {
    await pyodide.runPythonAsync(PREAMBLE);
    const figJson = pyodide.globals.get('__cs_result') as string;
    const fig = JSON.parse(figJson);
    return { figure: { data: fig.data ?? [], layout: fig.layout ?? {} } };
  } catch (e) {
    // Pyodide surfaces the Python traceback in the error message.
    return { error: (e as Error).message };
  }
}
