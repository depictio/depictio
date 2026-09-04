/**
 * PoC app (issue #945): one xy scatter fed by data loaded through the real
 * Depictio read path (load_deltatable_lite -> build_payload, see
 * poc/gen_poc_assets.py), mounted from React 18, with:
 *   - lasso/box selection -> InteractiveFilter-shaped emission (logged + shown)
 *   - Mantine-style light/dark toggle driving --chart-* tokens + .dark class
 *     (color values mirror plotlyTheme.ts's formula; a real integration would
 *     read them from useMantineColorScheme()/theme instead of constants)
 */

import { StrictMode, useCallback, useState } from "react";
import { createRoot } from "react-dom/client";

import { InteractiveFilterLike, XyChart } from "./XyChart";

// plotlyTheme.ts color formula (Mantine default theme gray[2]/gray[8])
const THEME_TOKENS = {
  light: { text: "#343a40", grid: "rgba(0,0,0,0.08)", body: "#ffffff" },
  dark: { text: "#e9ecef", grid: "rgba(255,255,255,0.08)", body: "#1a1b1e" },
};

declare global {
  interface Window {
    __pocFilters: InteractiveFilterLike[];
    __pocIds: string[];
  }
}
window.__pocFilters = [];

function App() {
  const [dark, setDark] = useState(false);
  const [lastFilter, setLastFilter] = useState<InteractiveFilterLike | null>(null);

  const toggleTheme = useCallback(() => {
    const next = !dark;
    setDark(next);
    const t = THEME_TOKENS[next ? "dark" : "light"];
    const rootEl = document.documentElement;
    rootEl.classList.toggle("dark", next);
    document.body.style.background = t.body;
    document.body.style.color = t.text;
    for (const [k, v] of Object.entries({
      "--chart-text": t.text,
      "--chart-grid": t.grid,
      "--chart-axis": t.grid,
      "--chart-bg": "rgba(0,0,0,0)",
    })) {
      rootEl.style.setProperty(k, v);
    }
  }, [dark]);

  const onFilterChange = useCallback((f: InteractiveFilterLike) => {
    window.__pocFilters.push(f);
    setLastFilter(f);
  }, []);

  return (
    <StrictMode>
      <div style={{ padding: 16, fontFamily: "system-ui, sans-serif" }}>
        <h3 style={{ margin: "0 0 8px" }}>
          xy in React 18 — no Reflex (depictio#945 PoC)
        </h3>
        <button id="theme-toggle" onClick={toggleTheme}>
          Switch to {dark ? "light" : "dark"}
        </button>
        <div style={{ width: 900, height: 460, marginTop: 12 }}>
          <XyChart
            componentIndex="poc-xy-scatter"
            specUrl="./poc_spec.json"
            blobUrl="./poc_blob.bin"
            ids={window.__pocIds ?? []}
            selectionColumn="individual_id"
            onFilterChange={onFilterChange}
          />
        </div>
        <pre id="filter-log" style={{ fontSize: 12, maxHeight: 140, overflow: "auto" }}>
          {lastFilter
            ? JSON.stringify(
                {
                  ...lastFilter,
                  value:
                    lastFilter.value.length > 8
                      ? [...lastFilter.value.slice(0, 8), `… ${lastFilter.value.length} total`]
                      : lastFilter.value,
                },
                null,
                2,
              )
            : "shift+drag on the chart to select points"}
        </pre>
      </div>
    </StrictMode>
  );
}

async function boot() {
  window.__pocIds = await fetch("./poc_ids.json").then((r) => r.json());
  createRoot(document.getElementById("root")!).render(<App />);
}

void boot();
