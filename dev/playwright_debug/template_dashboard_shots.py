#!/usr/bin/env python3
"""Capture one screenshot per tab of a shipped template dashboard.

The nf-core templates each ship `docs/dashboards.md`, a walkthrough that reads far
better next to a picture of the tab it describes. This drives the React viewer over a
locally ingested template project and writes `docs/screenshots/<tab-slug>.png` beside
that walkthrough.

Prerequisites:
    - the stack that ingested the template is running, and the API has been restarted
      since the last catalog tool was added (`load_catalog_entries` is lru_cached, so a
      tool added while the API ran leaves `viz_kind` null and the tile renders as
      "Unknown advanced viz kind")
    - the dashboards on the server are up to date with the YAML (`depictio dashboard
      import <base.yaml> --overwrite`)

Usage:
    python dev/playwright_debug/template_dashboard_shots.py \\
        --template nf-core/atacseq/1.2.2 \\
        --viewer-url http://localhost:5601 --api-url http://localhost:8101

    # every template that has a docs/ directory
    python dev/playwright_debug/template_dashboard_shots.py --all ...

    # an ingested showcase project, straight into a depictio-docs checkout
    python dev/playwright_debug/template_dashboard_shots.py \
        --scenario-prefix w3- --pipeline ampliseq --pipeline viralrecon \
        --cli-config ~/.depictio/CLI.<instance>.yaml \
        --viewer-url http://localhost:5612 --api-url http://localhost:8112 \
        --docs-root ../depictio-docs-worktrees/<branch> --theme dark

Project mode (`--project-name` / `--scenario-prefix`) lists the tabs through the API
and loads every tab by its own URL in a fresh browser context, with every grid section
and pinned section forced open, so the capture shows the whole tab. Outputs are named
`<tab_slug>_<theme>.png`; the MultiQC tab is always `multiqc`.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import urllib.request
from pathlib import Path

import typer
import yaml
from playwright.async_api import Page, async_playwright

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from depictio.api.v1.services.screenshot_helpers import (  # noqa: E402
    build_localstorage_init_script,
    dismiss_notifications,
    wait_for_dashboard_content,
    wait_for_panels_settled,
    wait_for_plotly_drawn,
)

PROJECTS_DIR = REPO_ROOT / "depictio" / "projects"
ADMIN_CONFIG_PATH = REPO_ROOT / "depictio" / ".depictio" / "admin_config.yaml"

app = typer.Typer(add_completion=False)


def slugify(name: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", name.lower())).strip("-")


def token_payload(config_path: Path | None = None) -> str:
    """The JSON blob the SPA expects in localStorage.

    Read from admin_config by default, or from a CLI config (`~/.depictio/CLI.*.yaml`),
    which nests the same token under `user.token`.
    """
    path = config_path or ADMIN_CONFIG_PATH
    if not path.exists():
        raise typer.BadParameter(f"config not found at {path}")
    cfg = yaml.safe_load(path.read_text())
    return json.dumps(cfg["user"]["token"] if "user" in cfg else cfg)


def api_get(api_url: str, path: str, token: str):
    req = urllib.request.Request(
        f"{api_url}/depictio/api/v1{path}", headers={"Authorization": f"Bearer {token}"}
    )
    return json.load(urllib.request.urlopen(req))


def resolve_dashboard(api_url: str, token: str, project_tag: str) -> str:
    """The dashboard id for a template, matched on the project name its YAML declares."""
    projects = api_get(api_url, "/projects/get/all", token)
    by_name = {p.get("name"): (p.get("_id") or p.get("id")) for p in projects}
    if project_tag not in by_name:
        raise typer.BadParameter(
            f"no project named {project_tag!r} on {api_url}; ingest the template first"
        )
    pid = by_name[project_tag]
    dashboards = [
        d for d in api_get(api_url, "/dashboards/list", token) if d.get("project_id") == pid
    ]
    if not dashboards:
        raise typer.BadParameter(f"project {project_tag!r} has no dashboard")
    return dashboards[0]["dashboard_id"]


def templates_with_docs() -> list[str]:
    out = []
    for docs in sorted(PROJECTS_DIR.glob("nf-core/*/*/docs")):
        version_dir = docs.parent
        if (version_dir / "dashboards" / "base.yaml").exists():
            out.append(str(version_dir.relative_to(PROJECTS_DIR)))
    return out


def shrink_png(path: Path) -> None:
    """Quantise a capture to a 256-colour palette.

    A full tab at 1680 px wide runs to a megabyte of truecolour PNG, and these live in
    the repo next to the walkthrough that embeds them. Flat UI screenshots quantise
    without a visible difference, which is worth roughly a two-thirds saving.
    """
    try:
        from PIL import Image
    except ImportError:  # optimisation only, never a reason to lose the capture
        return
    with Image.open(path) as im:
        im.convert("RGB").quantize(colors=256, method=Image.Quantize.MEDIANCUT).save(
            path, optimize=True
        )


def trim_bottom(path: Path, margin: int = 40, min_gap: int = 160) -> None:
    """Crop the blank band react-grid-layout leaves under the last panel.

    Growing the viewport to the scroller's full height also captures the slack
    below the lowest tile. Scan the content column (right of the filter sidebar,
    left of the floating buttons) upwards for the last row that differs from the
    bottom row, and cut a little below it when the band is tall enough to matter.
    """
    try:
        from PIL import Image, ImageChops
    except ImportError:
        return
    with Image.open(path) as im:
        rgb = im.convert("RGB")
    w, h = rgb.size
    column = rgb.crop((int(w * 0.25), 0, int(w * 0.95), h))
    background = Image.new("RGB", column.size, column.getpixel((column.width // 2, h - 1)))
    box = (
        ImageChops.difference(column, background)
        .convert("L")
        .point(lambda v: 255 if v > 12 else 0)
        .getbbox()
    )
    if not box:
        return
    bottom = min(h, box[3] + margin)
    if h - bottom >= min_gap:
        rgb.crop((0, 0, w, bottom)).save(path)


#: depictio-docs refuses files above 2000 kB in pre-commit; warn a little before that.
DOCS_WARN_KB = 1900
DOCS_IMAGE_DIR = Path("docs") / "images" / "pipeline-templates" / "nf-core"

# `<prefix><pipeline>-<version>-<scenario>`, the `Scenario.key` naming of
# scripts/nfcore_showcase.py with the prefix it was ingested under.
SCENARIO_RE = r"^{prefix}(?P<pipeline>[a-z0-9_]+)-(?P<version>\d[\w.]*)-(?P<scenario>.+)$"


def docs_slug(title: str) -> str:
    """The depictio-docs image name for a tab: lowercase, underscores, MultiQC -> `multiqc`."""
    if "multiqc" in title.lower():
        return "multiqc"
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", title.lower())).strip("_")


def expand_sections_script(dashboard_ids: list[str], family_id: str) -> str:
    """Seed every collapse store with "nothing collapsed" before first paint.

    `useCollapseState` stores the *collapsed* keys and only falls back to the
    author's `collapsed: true` defaults when nothing is stored, so an empty list
    opens every section. Grid sections are keyed per tab
    (`grid-section-collapsed:<dashboardId>`, DashboardGrid) and pinned sections per
    tab family (`grid-section-collapsed:<parentId>:persistent:<top|bottom>`,
    PersistentSectionsHost, where the family id is the main tab's dashboard id).
    """
    keys = [f"grid-section-collapsed:{d}" for d in dashboard_ids]
    keys += [f"grid-section-collapsed:{family_id}:persistent:{slot}" for slot in ("top", "bottom")]
    return "".join(f"localStorage.setItem({json.dumps(k)}, '[]');" for k in keys)


# Toasts are removed once by `dismiss_notifications`, but one raised after that
# (a late fetch warning) would land in the shot; keep the container hidden too.
HIDE_TOASTS_CSS = (
    ".mantine-Notifications-root, [data-mantine-notification-root] { display: none !important; }"
)


def resolve_projects(
    api_url: str, token: str, project_names: list[str], prefix: str, pipelines: list[str]
) -> list[tuple[str, str, str]]:
    """(pipeline, project name, project id) for each project asked for.

    Exact names win; otherwise every project named `<prefix><pipeline>-<version>-<scenario>`,
    narrowed to `pipelines` when given. A pipeline matching more than one scenario is an
    error rather than a silent pick.
    """
    projects = api_get(api_url, "/projects/get/all", token)
    by_name = {p.get("name"): (p.get("_id") or p.get("id")) for p in projects}
    out: list[tuple[str, str, str]] = []
    for name in project_names:
        if name not in by_name:
            raise typer.BadParameter(f"no project named {name!r} on {api_url}")
        m = re.match(SCENARIO_RE.format(prefix=re.escape(prefix)), name)
        pipeline = m.group("pipeline") if m else name.split("-")[0]
        out.append((pipeline, name, by_name[name]))
    if prefix and not project_names:
        pattern = re.compile(SCENARIO_RE.format(prefix=re.escape(prefix)))
        found: dict[str, list[str]] = {}
        for name in sorted(n for n in by_name if n):
            m = pattern.match(name)
            if m and (not pipelines or m.group("pipeline") in pipelines):
                found.setdefault(m.group("pipeline"), []).append(name)
        missing = [p for p in pipelines if p not in found]
        if missing:
            raise typer.BadParameter(f"no {prefix}* project for: {', '.join(missing)}")
        for pipeline, names in found.items():
            if len(names) > 1:
                raise typer.BadParameter(
                    f"{pipeline}: several scenarios ({', '.join(names)}); pass --project-name"
                )
            out.append((pipeline, names[0], by_name[names[0]]))
    return out


def list_tabs(api_url: str, token: str, project_id: str) -> tuple[str, list[tuple[str, str]]]:
    """(parent id, [(tab title, dashboard id)]): the main tab first, then by tab_order."""
    mains = [
        d
        for d in api_get(api_url, "/dashboards/list", token)
        if d.get("project_id") == project_id
        and d.get("is_main_tab", True)
        and not d.get("parent_dashboard_id")
    ]
    if not mains:
        raise typer.BadParameter(f"project {project_id} has no dashboard")
    tabs = api_get(api_url, f"/dashboards/tabs/{mains[0]['dashboard_id']}", token)
    main = tabs["main_tab"]
    # The main tab's `title` is the dashboard's; the tab strip shows `main_tab_name`.
    ordered = [(main.get("main_tab_name") or main["title"], main["dashboard_id"])]
    children = sorted(tabs.get("child_tabs", []), key=lambda t: t.get("tab_order") or 0)
    ordered += [(t["title"], t["dashboard_id"]) for t in children]
    return main["dashboard_id"], ordered


async def capture_loaded_tab(
    page: Page,
    path: Path,
    width: int,
    height_hint: int,
    max_height: int,
    panel_timeout_ms: int,
) -> int:
    """Wait for the tab on screen to finish, grow to its full height, write the PNG.

    Returns the captured height in CSS pixels.
    """
    await wait_for_dashboard_content(page)
    # Before the Plotly check, not after: a MultiQC panel that is still
    # preparing has no Plotly div for that check to wait on, and the
    # capture would show its "Preparing MultiQC figures…" placeholder.
    await wait_for_panels_settled(page, timeout_ms=panel_timeout_ms)
    await wait_for_plotly_drawn(page, timeout_ms=8_000)
    await dismiss_notifications(page)
    # The page itself never scrolls: `[data-testid="dashboard-content"]` is the
    # scroller, so `document.body.scrollHeight` is always one viewport and a
    # full_page capture would silently show only the top of the tab. Grow the
    # viewport by the container's hidden overflow instead, which is what makes
    # the whole tab paint, then clip to the ceiling the caller asked for. Tall
    # tabs take several rounds: panels that mount on growth add height of their own.
    for _ in range(6):
        over = await page.evaluate(
            "() => { const e = document.querySelector('[data-testid=\"dashboard-content\"]');"
            " return e ? e.scrollHeight - e.clientHeight : 0; }"
        )
        if over <= 4:
            break
        size = page.viewport_size or {"width": width, "height": height_hint}
        grown = min(size["height"] + over, max_height)
        if grown <= size["height"]:
            break
        await page.set_viewport_size({"width": width, "height": grown})
        await page.wait_for_timeout(1_200)
    # Growing the viewport brings panels into view that the indicator was
    # not counting, so it remounts and has to settle a second time.
    await wait_for_panels_settled(page, timeout_ms=panel_timeout_ms)
    await wait_for_plotly_drawn(page, timeout_ms=10_000)
    await dismiss_notifications(page)
    await page.evaluate(
        "() => { const e = document.querySelector('[data-testid=\"dashboard-content\"]');"
        " if (e) e.scrollTop = 0; window.scrollTo(0, 0); }"
    )
    await page.wait_for_timeout(800)
    await page.screenshot(path=str(path))
    trim_bottom(path)
    shrink_png(path)
    shot_h = (page.viewport_size or {}).get("height") or 0
    await page.set_viewport_size({"width": width, "height": height_hint})
    await page.wait_for_timeout(700)
    kb = path.stat().st_size // 1024
    warn = f"  ! over {DOCS_WARN_KB} kB" if kb > DOCS_WARN_KB else ""
    typer.echo(f"    ✓ {path.name} ({shot_h}px, {kb} kB){warn}")
    return shot_h


async def shoot_tabs(
    page: Page,
    out_dir: Path,
    width: int,
    height: int,
    max_height: int,
    settle_ms: int,
    panel_timeout_ms: int,
) -> list[Path]:
    """One capture per tab, in the order the tab bar shows them."""
    written: list[Path] = []
    labels = [t.strip() for t in await page.locator('[role="tab"]').all_inner_texts()]
    labels = [t for t in labels if t]
    typer.echo(f"    tabs: {labels}")
    for i, label in enumerate(labels):
        if i:
            # The tab bar sits in a sticky header, so a click attempted from a
            # scrolled position reports "element is outside of the viewport" and
            # retries until it times out. Go back to the top first, and fall back to
            # a dispatched event if the strip is still mid-animation.
            await page.evaluate("window.scrollTo(0, 0)")
            await page.wait_for_timeout(400)
            tab = page.locator('[role="tab"]', has_text=re.compile(rf"^{re.escape(label)}$")).first
            await tab.scroll_into_view_if_needed()
            try:
                await tab.click(timeout=10_000)
            except Exception:
                await tab.dispatch_event("click")
            await page.wait_for_timeout(settle_ms)
        path = out_dir / f"{slugify(label)}.png"
        await capture_loaded_tab(page, path, width, height, max_height, panel_timeout_ms)
        written.append(path)
    return written


async def run_one(
    template: str,
    viewer_url: str,
    api_url: str,
    theme: str,
    width: int,
    height: int,
    max_height: int,
    settle_ms: int,
    panel_timeout_ms: int,
    headless: bool,
    project_prefix: str = "",
) -> None:
    version_dir = PROJECTS_DIR / template
    base = version_dir / "dashboards" / "base.yaml"
    doc = yaml.safe_load(base.read_text())
    project_tag = doc["main_dashboard"]["project_tag"]
    if project_prefix:
        # Ingested with `--project-name <prefix><pipeline>` instead of the YAML's name.
        project_tag = f"{project_prefix}{template.split('/')[1]}"
    payload = token_payload()
    token = json.loads(payload).get("access_token")
    dashboard_id = resolve_dashboard(api_url, token, project_tag)
    out_dir = version_dir / "docs" / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)
    typer.echo(f"  {template} -> {project_tag} / {dashboard_id}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(viewport={"width": width, "height": height})
        # Seed auth and theme before first paint: the SPA reads both in initialisers.
        await context.add_init_script(build_localstorage_init_script(payload, theme))
        page = await context.new_page()
        await page.goto(f"{viewer_url}/dashboard/{dashboard_id}", wait_until="domcontentloaded")
        await page.wait_for_timeout(settle_ms * 2)
        await shoot_tabs(page, out_dir, width, height, max_height, settle_ms, panel_timeout_ms)
        await browser.close()


async def run_project(
    pipeline: str,
    project_name: str,
    project_id: str,
    payload: str,
    out_dir: Path,
    viewer_url: str,
    api_url: str,
    theme: str,
    width: int,
    height: int,
    max_height: int,
    scale: float,
    settle_ms: int,
    panel_timeout_ms: int,
    headless: bool,
    only_tabs: list[str],
) -> None:
    """Every tab of one ingested project, each loaded by URL in a fresh context."""
    token = json.loads(payload).get("access_token")
    parent_id, tabs = list_tabs(api_url, token, project_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    typer.echo(f"  {pipeline}: {project_name} / {parent_id} ({len(tabs)} tabs) -> {out_dir}")
    init = build_localstorage_init_script(payload, theme) + expand_sections_script(
        [d for _, d in tabs], parent_id
    )
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        for title, dashboard_id in tabs:
            slug = docs_slug(title)
            if only_tabs and slug not in only_tabs and title not in only_tabs:
                continue
            # A fresh context per tab: no selection, group or filter state carries
            # over from the tab before, and the collapse seed applies again.
            context = await browser.new_context(
                viewport={"width": width, "height": height}, device_scale_factor=scale
            )
            await context.add_init_script(init)
            page = await context.new_page()
            try:
                await page.goto(
                    f"{viewer_url}/dashboard/{dashboard_id}", wait_until="domcontentloaded"
                )
                await page.add_style_tag(content=HIDE_TOASTS_CSS)
                await page.wait_for_timeout(settle_ms)
                await capture_loaded_tab(
                    page,
                    out_dir / f"{slug}_{theme}.png",
                    width,
                    height,
                    max_height,
                    panel_timeout_ms,
                )
            except Exception as exc:  # one bad tab must not sink the project
                typer.echo(f"    ✗ {title}: {exc}", err=True)
            finally:
                await context.close()
        await browser.close()


@app.command()
def main(
    template: list[str] = typer.Option([], "--template", help="nf-core/<pipeline>/<version>"),
    every: bool = typer.Option(False, "--all", help="every template that ships a docs/ dir"),
    viewer_url: str = typer.Option("http://localhost:5601"),
    api_url: str = typer.Option("http://localhost:8101"),
    theme: str = typer.Option("light"),
    width: int = typer.Option(1680),
    height: int = typer.Option(1250),
    max_height: int = typer.Option(20000, help="clip taller tabs to this many pixels"),
    scale: float = typer.Option(1.0, help="device scale factor (project mode)"),
    settle_ms: int = typer.Option(3500, help="pause after navigation and each tab click"),
    panel_timeout_ms: int = typer.Option(
        120_000, help="how long to let a tab's panels finish loading before capturing"
    ),
    headless: bool = typer.Option(True, "--headless/--headed"),
    project_prefix: str = typer.Option(
        "",
        help="match projects ingested as <prefix><pipeline> (e.g. lot2-) instead of the YAML name",
    ),
    project_name: list[str] = typer.Option(
        [], "--project-name", help="project mode: an ingested project, by exact name"
    ),
    scenario_prefix: str = typer.Option(
        "",
        "--scenario-prefix",
        help="project mode: projects named <prefix><pipeline>-<version>-<scenario> "
        "(nfcore_showcase.py Scenario.key); narrow with --pipeline",
    ),
    pipeline: list[str] = typer.Option([], "--pipeline", help="with --scenario-prefix"),
    tab: list[str] = typer.Option(
        [], "--tab", help="project mode: only these tabs (docs slug or exact title)"
    ),
    cli_config: Path | None = typer.Option(
        None, "--cli-config", help="auth from a CLI config (user.token) instead of admin_config"
    ),
    docs_root: Path | None = typer.Option(
        None,
        "--docs-root",
        help="project mode: a depictio-docs checkout; writes "
        "docs/images/pipeline-templates/nf-core/<pipeline>/<slug>_<theme>.png",
    ),
    out_dir: Path = typer.Option(
        REPO_ROOT / "dev" / "playwright_debug" / "template_shots",
        help="project mode without --docs-root: <out-dir>/<project>/",
    ),
) -> None:
    if project_name or scenario_prefix:
        payload = token_payload(cli_config.expanduser() if cli_config else None)
        token = json.loads(payload).get("access_token")
        targets = resolve_projects(api_url, token, project_name, scenario_prefix, pipeline)
        typer.echo(f"capturing {len(targets)} projects ({theme})")
        for pipe, name, pid in targets:
            dest = docs_root.expanduser() / DOCS_IMAGE_DIR / pipe if docs_root else out_dir / name
            try:
                asyncio.run(
                    run_project(
                        pipe,
                        name,
                        pid,
                        payload,
                        dest,
                        viewer_url,
                        api_url,
                        theme,
                        width,
                        height,
                        max_height,
                        scale,
                        settle_ms,
                        panel_timeout_ms,
                        headless,
                        tab,
                    )
                )
            except Exception as exc:  # one bad project must not sink the batch
                typer.echo(f"  ✗ {name}: {exc}", err=True)
        return
    names = templates_with_docs() if every else list(template)
    if not names:
        raise typer.BadParameter("pass --template <id> at least once, or --all")
    typer.echo(f"capturing {len(names)} template dashboards")
    for name in names:
        try:
            asyncio.run(
                run_one(
                    name,
                    viewer_url,
                    api_url,
                    theme,
                    width,
                    height,
                    max_height,
                    settle_ms,
                    panel_timeout_ms,
                    headless,
                    project_prefix,
                )
            )
        except Exception as exc:  # one bad template must not sink the batch
            typer.echo(f"  ✗ {name}: {exc}", err=True)


if __name__ == "__main__":
    app()
