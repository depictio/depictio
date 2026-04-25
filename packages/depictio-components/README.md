# depictio-components

Shared React components for Depictio dashboards. One source of truth rendered by both the Dash editor (via Python wrappers) and the React viewer (direct TS import).

## Layout

```
packages/depictio-components/
├── src/lib/components/        # React source (TSX) — ground truth
│   ├── DepictioCard.tsx
│   └── DepictioMultiSelect.tsx
├── depictio_components/       # Python wrappers (Dash component protocol)
│   ├── __init__.py
│   ├── DepictioCard.py
│   └── DepictioMultiSelect.py
│   └── depictio_components.min.js  # built JS bundle (output of npm run build:js)
├── package.json
├── webpack.config.js
├── tsconfig.json
└── pyproject.toml
```

## Build

Node.js >= 20 and npm >= 10 required.

```bash
cd packages/depictio-components
npm install
npm run build     # produces depictio_components/depictio_components.min.js
```

The Python package is installed by the root `uv sync` via the `[tool.uv.sources]` entry in the top-level `pyproject.toml`.

## Use from Dash

```python
from depictio_components import DepictioCard, DepictioMultiSelect

layout = DepictioCard(
    id={"type": "card-component", "index": "uuid-here"},
    title="Total Samples",
    value=4508,
    icon_name="mdi:counter",
    title_color="#9C27B0",
)
```

Pattern-matched IDs work as usual. Value updates from Dash callbacks set the `value` prop and React re-renders.

## Use from React viewer

```tsx
import { DepictioCard, DepictioMultiSelect } from 'depictio-components';

<DepictioCard title="Total Samples" value={4508} icon_name="mdi:counter" />
```

## Props match Depictio's stored_metadata keys

Snake_case prop names mirror `Dashboard.stored_metadata` keys one-to-one (`title_color`, `icon_name`, `background_color`, `column_name`, `interactive_component_type`). The React viewer fetches `stored_metadata` from `/depictio/api/v1/dashboards/get/{id}` and spreads it onto the component — no translation layer.

## Adding a new component

1. Write `src/lib/components/MyNewComponent.tsx` with a `Props` interface.
2. Export from `src/lib/index.ts` and attach to the `window.depictio_components` global.
3. Write `depictio_components/MyNewComponent.py` — a `Component` subclass mirroring the TSX props.
4. Add to `depictio_components/__init__.py` exports.
5. `npm run build`.

Long-term: `npm run build:py` (script to write) will auto-generate the Python wrappers from TSX props via `react-docgen-typescript`. For the MVP they're hand-written.
