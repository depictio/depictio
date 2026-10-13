# Branding a deployment

Depictio ships in a neutral Mantine look. A deployment can replace that with
its own identity — logo, name, colors, chrome surfaces, typography and figure
palette — and a single dashboard can override any of it for itself.

Everything is expressed as one object, the **brand theme**, so the three places
you can set it (deployment environment, the `/admin` Branding panel, a
dashboard's Settings drawer) all take the same fields.

## Where it can be set

```
Mantine defaults  <-  DEPICTIO_BRANDING_*  <-  /admin overrides  <-  dashboard
```

Each layer states only what differs; anything it leaves out is inherited from
the layer to its left. That is what makes a dashboard's "Inherit instance"
setting real rather than a copy: change the instance logo and every dashboard
that never uploaded its own follows.

| Layer | Set from | Needs a redeploy |
| --- | --- | --- |
| Deployment defaults | `DEPICTIO_BRANDING_*` env vars (see `.env.example`, or `helm-charts/depictio/examples/values-branding.yaml`) | Yes |
| Instance overrides | `/admin` -> Branding, saved server-side | No |
| Dashboard override | The dashboard's Settings drawer, or `brand_theme:` in its YAML | No |

## The fields

**Identity.** `app_name` (browser tab title and login greeting), `logo_url`,
`logo_url_dark`, and `logo_mode` — `inherit` (the default), `custom` or `none`.
A dashboard set to `none` shows no logo even when the instance has one.

**Brand palette.** `primary`, `secondary`, `tertiary` — a hex color or a
Mantine palette name (`blue`, `teal`, `grape`, ...).

**Status colors.** `success`, `warning`, `danger`. These sit deliberately
outside the brand reach below, because pass / warn / fail have to keep reading
as meaning rather than as decoration. Set them only if your brand has its own.

**Reach** (`tint_mode`). How far the brand hues travel into the app's existing
accents:

- `accent` (default) re-tints the primary accent only. The app keeps its
  familiar secondary accents.
- `full` additionally gives the secondary and tertiary the app's `teal` and
  `orange` accent families, so buttons, tabs, badges and section accents follow
  all three brand colors. `gray`, `red`, `green` and `yellow` are never
  remapped in either mode.

**Surfaces** (`surfaces_light`, `surfaces_dark`). Per color scheme:
`app_bg` (page background), `section_bg` (cards, panels, section accordions),
`nav_bg` (header and sidebar) and `heading` (title text). Hex only — these
become raw CSS values. Left unset, Mantine's own scheme colors apply.

**Typography and shape.** `font_family`, `headings_font_family` and
`default_radius` (a Mantine token, `xs` to `xl`). A named font has to be
installed or served by the deployment — none is fetched for you.

**Figures** (`plots`). `template` is the Plotly template for figures whose
component picks none; unset means "follow the UI color scheme", which is
Depictio's own brand-aware `mantine_light` / `mantine_dark`. `colorway` and
`sequential` are the categorical and continuous palettes.

## Derived values

`colorway`, `sequential` and the Mantine shade tuples are **derived from the
brand palette** whenever you do not state them, so figures follow the brand
without a second list to keep in step.

The derivation runs server-side, once, and the resolved theme is what
`/utils/public-config` serves — the browser never re-derives anything, so the
figures a dashboard renders and the buttons around them cannot drift apart.

Two details worth knowing:

- A hex brand color is expanded into a full 10-shade Mantine tuple with **your
  color on shade 6**, which is the shade a filled control actually paints in
  light mode (shade 8 in dark). Generic palette generators place the input by
  its lightness instead, which for a dark brand leaves every button a
  washed-out cousin of it.
- The categorical colorway walks the brand hues first and only then rotates
  hue, so the first few series in a figure are recognisably the brand.

State `colorway` or `sequential` yourself and the derivation steps aside for
that field alone.

## Presets, import and export

`/admin` -> Branding ships a few starting points — the stock Depictio look,
TREC, EMBL and Ocean — reachable from the **Presets** menu, and settable at
deploy time with `DEPICTIO_BRANDING_PRESET`. A preset is only a form seed:
everything it fills in stays editable, and the flat env vars override it field
by field.

**Export** writes the current theme as JSON and **Import** reads one back, so a
brand can be reviewed, version-controlled and moved between deployments. An
imported file keeps the instance's uploaded logos unless it names logos of its
own, on the same reasoning as a preset: a theme file is a palette, not an
identity.

## Where the logos live

Uploaded logos are stored in MongoDB, in a `branding_assets` collection, and
served from the API (`/utils/branding/logo/{variant}` for the instance,
`/dashboards/logo/{id}` for a dashboard). Nothing is written to the container's
filesystem, so a rebuild or a pod redeploy cannot leave a theme pointing at an
image that no longer exists, and no volume or PVC has to be provisioned for
them. They are capped at 2 MB each (PNG, JPEG or WebP; SVG is refused because
it can carry scripts and would be served same-origin).

Both `branding_assets` and the overrides document in `instance_settings` are
part of the backup set, so a restore brings back the instance identity that
every dashboard's own theme inherits from.

Deployments branded before this moved keep working: logos still on disk are
imported into the database at startup and their stored URLs rewritten, once.

## The "Powered by Depictio" attribution

The badge is not always shown. It appears exactly when the Depictio wordmark
does not: on a stock deployment the wordmark is already in the app rail and on
the login card, so a badge repeating it would be noise, and on a branded one it
is the only thing left saying what the app is built on.

Concretely, it renders when the logo in scope resolves to `custom` or `none`,
and it appears once per surface: on the login card under the logo, in the app
rail outside dashboards, and in the header of a dashboard.

## A dashboard override

From a dashboard in edit mode: Settings -> Appearance -> Branding ->
**Customise**. The same fields appear, with the instance's values shown as
placeholders, and the live preview beside them renders real components under
the draft.

The override applies to that dashboard's page only — the dashboard list, the
admin pages and every other dashboard stay on the instance theme.

In YAML, it is a `brand_theme:` block at the top level. The penguins demo
dashboard carries one as a worked example:

```yaml
brand_theme:
  primary: "#159090"    # Gentoo
  secondary: "#a034f0"  # Chinstrap
  tertiary: "#ff8c00"   # Adelie
  tint_mode: "full"
```

Logos uploaded through the UI are stripped on export, since the file lives on
the instance that received it and would resolve to nothing elsewhere.
