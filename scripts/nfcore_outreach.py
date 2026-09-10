#!/usr/bin/env python3
"""Prepare the maintainer review round for nf-core template dashboards.

Maintainer/CI tool (NOT part of the shipped ``depictio-cli`` package). Once a
pipeline's template, dashboard and docs page are ready, the people whose
opinion decides whether it is *right* are that pipeline's nf-core maintainers.
This script turns what is already in the repo into the material that review
round needs, one bundle per pipeline:

* a one-pager — what the dashboard shows, what it reads out of a run, which
  pipeline routes the template variables cover — rendered as a GitHub
  Discussion body,
* a short draft for the pipeline's ``#<pipeline>`` channel on the nf-core
  Slack, which is where maintainers actually read things,
* a tracking table for the round's epic issue, regenerable as the round moves.

Every fact is derived from ``depictio/projects/nf-core/<pipeline>/<version>/``
(the template, its dashboards, its megatest manifest, its docs page), so a
bundle cannot drift from what is shipped: re-run it and the tables follow the
YAML.

Nothing is published by default. ``--create-discussions`` is the only flag that
writes to GitHub; it needs ``gh`` authenticated against the repo, and it skips
a pipeline that already has a discussion with the same title, so re-running it
is safe.

Usage::

    python scripts/nfcore_outreach.py                        # all pipelines -> dev/outreach/
    python scripts/nfcore_outreach.py --pipeline rnaseq --pipeline chipseq
    python scripts/nfcore_outreach.py --json                 # facts only, no files written
    python scripts/nfcore_outreach.py --create-discussions   # posts, once the bodies are reviewed
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator

# Import the in-repo helpers the same way nfcore_monitor does, so a direct
# `python scripts/nfcore_outreach.py` works without an editable install.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from nfcore_megatest import load_manifest, manifest_path  # noqa: E402
from nfcore_monitor import (  # noqa: E402
    NFCORE_PROJECTS_DIR,
    discover_pipelines,
    load_template,
    local_latest_version,
)

DEFAULT_OUT_DIR = _REPO_ROOT / "dev" / "outreach"
DEFAULT_INSTANCE = "https://demo.depictio.embl.org"
DEFAULT_DOCS_URL = (
    "https://depictio.github.io/depictio-docs/stable/pipeline-templates/nf-core/{pipeline}/"
)
DEFAULT_REPO = "depictio/depictio"
DEFAULT_CATEGORY = "Pipeline templates"
# Branch naming for the template PRs (`feat/nfcore-templates-<pipeline>`); the
# PR title is the fallback when a pipeline landed on a differently named branch.
PR_BRANCH_MARKER = "nfcore-templates-"

# How many headline metrics / sections to quote back in the review questions.
# The point is to give the reader something concrete to react to, not to
# reproduce the dashboard in the discussion body.
MAX_QUOTED_CARDS = 8
MAX_QUOTED_TOOLS = 12

# A pipeline flag named in a variable description ("mirrors --skip_multiqc").
_FLAG_RE = re.compile(r"--[a-z][a-z0-9_]*")


# ---------------------------------------------------------------------------
# Facts, read out of the shipped template
# ---------------------------------------------------------------------------
@dataclass
class Tab:
    """One dashboard tab: the ``main_dashboard`` itself, or one of its ``tabs``."""

    title: str
    subtitle: str
    sections: list[str] = field(default_factory=list)


@dataclass
class DashboardFacts:
    """One ``dashboards/*.yaml`` file and the tabs it declares."""

    file: str
    project_tag: str
    tabs: list[Tab] = field(default_factory=list)


@dataclass
class PipelineFacts:
    """Everything the outreach bundle for one pipeline is rendered from."""

    pipeline: str
    version: str
    template_id: str
    description: str
    required_vars: list[tuple[str, str]] = field(default_factory=list)
    optional_vars: list[tuple[str, str]] = field(default_factory=list)
    dashboards: list[DashboardFacts] = field(default_factory=list)
    data_collections: list[dict[str, Any]] = field(default_factory=list)
    catalog_tools: list[str] = field(default_factory=list)
    component_counts: dict[str, int] = field(default_factory=dict)
    card_titles: list[str] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    docs_page: str | None = None
    megatest_sha: str | None = None
    run_root: str = ""
    multiqc_version: str | None = None
    pr: dict[str, Any] | None = None

    @property
    def tabs(self) -> list[Tab]:
        """Every tab across every dashboard file, in declaration order."""
        return [tab for dashboard in self.dashboards for tab in dashboard.tabs]


def _repo_relative(path: Path) -> str:
    """Repo-relative when the path is inside the checkout, absolute otherwise.

    ``--projects-dir`` can point anywhere (it is how the tests drive this), and
    a path outside the repo has no repo-relative form.
    """
    try:
        return str(path.relative_to(_REPO_ROOT))
    except ValueError:
        return str(path)


def _template_block(template: dict) -> dict:
    return template.get("template", {}) or {}


def _variables(template: dict) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Split ``template.variables`` into required and optional ``(name, description)``.

    The optional ones are the interesting half for a maintainer: each covers a
    pipeline route the template had to be told about (``--skip_multiqc``,
    ``--skip_alignment``…), so together they are this template's claim about
    which parameter combinations it survives.
    """
    required: list[tuple[str, str]] = []
    optional: list[tuple[str, str]] = []
    for var in _template_block(template).get("variables", []) or []:
        entry = (str(var.get("name", "")), str(var.get("description", "")).strip())
        (required if var.get("required") else optional).append(entry)
    return required, optional


def _route_vars(optional: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The optional variables that stand for a pipeline route, not a path override.

    A route variable's description names the pipeline flag it mirrors
    (``--skip_multiqc``, ``--skip_alignment``), which is what makes the set
    answerable: "which of your users' parameter combinations are missing here?".
    A plain path override like ``SAMPLESHEET_FILE`` names none, and asking about
    it only muddies the question.
    """
    return [
        (name, description)
        for name, description in optional
        if [flag for flag in _FLAG_RE.findall(description) if flag != "--var"]
    ]


def _sections(node: dict) -> list[str]:
    """Grid section names for a tab, which is the tab's own outline."""
    return [
        str(section.get("name", ""))
        for section in (node.get("grid_sections") or [])
        if section.get("name")
    ]


def _tab_from_node(node: dict, title: str, subtitle: str) -> Tab:
    return Tab(title=title, subtitle=subtitle, sections=_sections(node))


def _iter_tab_nodes(doc: dict) -> Iterator[tuple[dict, str, str]]:
    """Yield ``(node, title, subtitle)`` for the main dashboard and each child tab."""
    main = doc.get("main_dashboard") or {}
    if main:
        # The main dashboard's own tab is named by `main_tab_name`; its `title`
        # names the whole dashboard, which is a different thing.
        yield (
            main,
            str(main.get("main_tab_name") or main.get("title") or "Main"),
            str(main.get("subtitle") or ""),
        )
    for tab in doc.get("tabs") or []:
        yield tab, str(tab.get("title") or ""), str(tab.get("subtitle") or "")


def _iter_components(doc: dict) -> Iterator[dict]:
    """Every component in a dashboard file, main tab and child tabs alike."""
    for node, _title, _subtitle in _iter_tab_nodes(doc):
        for component in node.get("components") or []:
            if isinstance(component, dict):
                yield component


def _load_dashboards(pipeline_dir: Path) -> list[tuple[str, dict]]:
    """Parse every ``dashboards/*.yaml``, sorted so `base.yaml` leads."""
    import yaml

    dashboards_dir = pipeline_dir / "dashboards"
    if not dashboards_dir.is_dir():
        return []
    files = sorted(
        dashboards_dir.glob("*.yaml"),
        # base.yaml is the entry dashboard wherever a template ships several.
        key=lambda p: (p.name != "base.yaml", p.name),
    )
    out: list[tuple[str, dict]] = []
    for path in files:
        try:
            doc = yaml.safe_load(path.read_text()) or {}
        except yaml.YAMLError as exc:  # noqa: PERF203 - one bad file must not sink the run
            print(f"  ! {path}: unreadable ({exc})", file=sys.stderr)
            continue
        if isinstance(doc, dict):
            out.append((path.name, doc))
    return out


def _reads_from(config: dict) -> tuple[str, str]:
    """``(how, what)`` for one data collection's input.

    Templates take input two ways: a recipe computes a table from run files
    (``source: transformed``), or the ingest scans the run directly for a file
    name or a pattern. Both halves matter to a maintainer — the second one is
    literally "these are the paths I expect your pipeline to publish" — so the
    table names the mechanism and the thing it points at.
    """
    if config.get("source") == "transformed":
        recipe = str((config.get("transform") or {}).get("recipe") or "")
        return "computed", f"`{recipe}`" if recipe else "—"
    scan_parameters = (config.get("scan") or {}).get("scan_parameters") or {}
    if "filename" in scan_parameters:
        return "scanned file", f"`{scan_parameters['filename']}`"
    pattern = (scan_parameters.get("regex_config") or {}).get("pattern")
    if pattern:
        return "scanned pattern", f"`{pattern}`"
    if str(config.get("type", "")).lower() == "multiqc":
        return "MultiQC report", "the run's own `multiqc_data`"
    return str(config.get("type") or "—"), "—"


def _data_collections(template: dict) -> list[dict[str, Any]]:
    """Flatten the template's data collections into the "what it reads" table.

    A maintainer can check this against what their pipeline actually publishes
    without opening the template.
    """
    rows: list[dict[str, Any]] = []
    for workflow in template.get("workflows", []) or []:
        for dc in workflow.get("data_collections", []) or []:
            config = dc.get("config", {}) or {}
            how, what = _reads_from(config)
            rows.append(
                {
                    "tag": str(dc.get("data_collection_tag", "")),
                    "description": " ".join(str(dc.get("description") or "").split()),
                    "how": how,
                    "reads": what,
                    "optional": bool(dc.get("optional")),
                }
            )
    return rows


def collect_facts(
    pipeline: str,
    version: str,
    projects_dir: Path = NFCORE_PROJECTS_DIR,
) -> PipelineFacts:
    """Read one pinned template version into the facts the bundle is rendered from."""
    pipeline_dir = projects_dir / pipeline / version
    template = load_template(pipeline, version, projects_dir=projects_dir)
    block = _template_block(template)
    required, optional = _variables(template)

    dashboards: list[DashboardFacts] = []
    counts: dict[str, int] = {}
    card_titles: list[str] = []
    tools: set[str] = set()
    for name, doc in _load_dashboards(pipeline_dir):
        main = doc.get("main_dashboard") or {}
        dashboards.append(
            DashboardFacts(
                file=name,
                project_tag=str(main.get("project_tag") or ""),
                tabs=[
                    _tab_from_node(node, title, subtitle)
                    for node, title, subtitle in _iter_tab_nodes(doc)
                ],
            )
        )
        for component in _iter_components(doc):
            kind = str(component.get("component_type") or "unknown")
            counts[kind] = counts.get(kind, 0) + 1
            if kind == "card" and component.get("title"):
                card_titles.append(str(component["title"]))
            # `use: <module>/<render>` is an advanced_viz's binding to a catalog
            # tool; the module half is the tool a maintainer would recognise.
            use = component.get("use")
            if isinstance(use, str) and "/" in use:
                tools.add(use.split("/", 1)[0])

    manifest_file = manifest_path(pipeline, version, projects_dir=projects_dir)
    megatest_sha = None
    run_root = ""
    multiqc_version = None
    if manifest_file.is_file():
        try:
            manifest = load_manifest(manifest_file)
        except ValueError as exc:
            print(f"  ! {manifest_file}: {exc}", file=sys.stderr)
        else:
            megatest_sha = manifest.results_sha
            run_root = manifest.run_root
            multiqc_version = (manifest.multiqc or {}).get("version")

    docs_page = pipeline_dir / "docs" / "dashboards.md"
    screenshots = sorted(
        _repo_relative(p) for p in (pipeline_dir / "docs" / "screenshots").glob("*.png")
    )

    return PipelineFacts(
        pipeline=pipeline,
        version=version,
        template_id=str(block.get("template_id") or f"nf-core/{pipeline}/{version}"),
        description=str(block.get("description") or "").strip(),
        required_vars=required,
        optional_vars=optional,
        dashboards=dashboards,
        data_collections=_data_collections(template),
        catalog_tools=sorted(tools),
        component_counts=dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        card_titles=card_titles,
        screenshots=screenshots,
        docs_page=_repo_relative(docs_page) if docs_page.is_file() else None,
        megatest_sha=megatest_sha,
        run_root=run_root,
        multiqc_version=str(multiqc_version) if multiqc_version else None,
    )


# ---------------------------------------------------------------------------
# The open pull request that ships each template
# ---------------------------------------------------------------------------
def fetch_pull_requests(repo: str) -> dict[str, dict[str, Any]]:
    """Map pipeline -> its open template PR, via ``gh``.

    Best-effort: a missing or unauthenticated ``gh`` leaves the PR column blank
    rather than failing the run, because the bundle is still useful without it.
    """
    if shutil.which("gh") is None:
        print("  ! gh not on PATH — PR links will be blank", file=sys.stderr)
        return {}
    try:
        raw = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "--repo",
                repo,
                "--limit",
                "100",
                "--json",
                "number,title,headRefName,url,isDraft",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        ).stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"  ! could not list PRs ({exc}) — PR links will be blank", file=sys.stderr)
        return {}

    out: dict[str, dict[str, Any]] = {}
    for pr in json.loads(raw or "[]"):
        branch = str(pr.get("headRefName", ""))
        if PR_BRANCH_MARKER not in branch:
            continue
        pipeline = branch.split(PR_BRANCH_MARKER, 1)[1].strip("/")
        # `feat/nfcore-templates-lot1` is the stack base, not a pipeline.
        if pipeline and not pipeline.startswith("lot"):
            out.setdefault(pipeline, pr)
    return out


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def project_tag(facts: PipelineFacts) -> str:
    """The project name the template's dashboards are filed under on a deployment."""
    return next((d.project_tag for d in facts.dashboards if d.project_tag), facts.pipeline)


def dashboard_url(facts: PipelineFacts, instance: str, urls: dict[str, str]) -> tuple[str, bool]:
    """``(url, is_deep_link)`` for where a reviewer clicks.

    Dashboard ids are minted per deployment, so they cannot be derived from the
    repo: pass the real per-pipeline links with ``--dashboard-urls``. Without
    them this degrades to the instance's dashboard list, which does work — the
    reviewer just has to pick the project out of it — and the epic table flags
    the pipeline as still needing a deep link.
    """
    url = urls.get(facts.pipeline)
    if url:
        return url, True
    return f"{instance.rstrip('/')}/dashboards", False


def load_dashboard_urls(path: str | None) -> dict[str, str]:
    """Read the ``{pipeline: url}`` map that turns the list link into a deep link."""
    if not path:
        return {}
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict):
        raise SystemExit(f"{path}: expected a JSON object of pipeline -> dashboard URL")
    return {str(k): str(v) for k, v in data.items()}


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "_(none)_\n"
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    out += ["| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |" for row in rows]
    return "\n".join(out) + "\n"


def _review_questions(facts: PipelineFacts) -> str:
    """Three questions grounded in this template's own content.

    An open "what do you think?" to a volunteer maintainer returns nothing.
    Each question quotes something specific back — the headline numbers, the
    tab outline, the routes the variables cover — so answering it is a
    correction rather than an essay.
    """
    cards = facts.card_titles[:MAX_QUOTED_CARDS]
    tabs = [t.title for t in facts.tabs if t.title]
    routes = [name for name, _ in _route_vars(facts.optional_vars)]

    lines = ["### What I would like your take on\n\n"]

    lines.append("**1. Is any of this wrong or misleading?** The headline numbers are:\n")
    lines.append(
        ", ".join(f"`{c}`" for c in cards) + "\n"
        if cards
        else "_(this template shows no summary cards)_\n"
    )
    lines.append(
        "\nA metric that is subtly wrong for your pipeline is the single most expensive "
        "thing to leave in, so please be blunt.\n"
    )

    lines.append("\n**2. What do you always look at that is not here?** The tabs are:\n")
    lines.append(", ".join(f"`{t}`" for t in tabs) + "\n" if tabs else "_(no tabs declared)_\n")
    lines.append(
        "\nI am after the one plot or table you open first when you debug a run of this "
        "pipeline, whether or not it is in MultiQC.\n"
    )

    lines.append("\n**3. Which real runs would this not fit?** The template adapts to:\n")
    if routes:
        lines.append(", ".join(f"`{r}`" for r in routes) + "\n")
        lines.append(
            "\nThose are the parameter combinations it was told about. Which ones that your "
            "users actually run are missing from that list?\n"
        )
    else:
        lines.append(
            "_(nothing yet — it assumes a default-profile run)_\n\nWhich parameter "
            "combinations do your users run that would break that assumption?\n"
        )
    return "".join(lines)


def render_discussion(
    facts: PipelineFacts,
    instance: str,
    docs_url_template: str,
    urls: dict[str, str],
) -> str:
    """The GitHub Discussion body: what it is, what to click, what I am asking."""
    docs_url = docs_url_template.format(pipeline=facts.pipeline, version=facts.version)
    live, deep = dashboard_url(facts, instance, urls)
    pr = facts.pr

    parts = [f"## nf-core/{facts.pipeline} {facts.version} as a Depictio dashboard\n\n"]
    if facts.description:
        parts.append(f"{facts.description}\n\n")

    where = "" if deep else f' (open the "{project_tag(facts)}" project)'
    parts.append(f"- **Try it live:** {live}{where}\n")
    parts.append(f"- **Docs:** {docs_url}\n")
    if pr:
        draft = " (draft)" if pr.get("isDraft") else ""
        parts.append(f"- **Template source:** {pr['url']}{draft}\n")
    parts.append(f"- **Template:** `depictio/projects/nf-core/{facts.pipeline}/{facts.version}/`\n")
    if facts.megatest_sha:
        root = f", run root `{facts.run_root}`" if facts.run_root else ""
        parts.append(
            f"- **Validated against:** the AWS megatest run "
            f"`s3://nf-core-awsmegatests/{facts.pipeline}/results-{facts.megatest_sha}/`{root}\n"
        )
    parts.append("\n")

    parts.append("### What the dashboard shows\n\n")
    parts.append(
        _md_table(
            ["Tab", "What it is about", "Sections"],
            [
                [t.title, t.subtitle or "—", ", ".join(t.sections) or "—"]
                for t in facts.tabs
                if t.title
            ],
        )
    )

    parts.append("\n### What it reads out of a run\n\n")
    parts.append(
        _md_table(
            ["Data collection", "How", "From", "Optional"],
            [
                [
                    f"`{row['tag']}`",
                    row["how"],
                    row["reads"],
                    "yes" if row["optional"] else "",
                ]
                for row in facts.data_collections
            ],
        )
    )
    parts.append(
        "\nThe scanned rows are the paths this template expects a run to publish "
        "(`{DATA_ROOT}` is the run directory; a pattern is matched anywhere under it). "
        "If any of them moved in a recent release, that is the first thing to tell me.\n"
    )
    if facts.catalog_tools:
        tools = ", ".join(f"`{t}`" for t in facts.catalog_tools[:MAX_QUOTED_TOOLS])
        parts.append(f"\nPurpose-built panels come from these tool modules: {tools}.\n")
    if facts.multiqc_version:
        parts.append(
            f"\nThe MultiQC panels are read from the run's own report (MultiQC "
            f"{facts.multiqc_version}), not recomputed.\n"
        )

    routes = _route_vars(facts.optional_vars)
    if routes:
        parts.append("\n### Runs it adapts to\n\n")
        parts.append(
            _md_table(
                ["Variable", "The route it covers"],
                [[f"`{name}`", desc or "—"] for name, desc in routes],
            )
        )

    parts.append("\n")
    parts.append(_review_questions(facts))
    parts.append(
        f"\n---\n\nNo account is needed to open the dashboard. If it is easier, reply in the "
        f"nf-core Slack `#{facts.pipeline}` channel and I will bring it back here so the "
        f"thread stays with the template.\n"
    )
    return "".join(parts)


def render_slack(
    facts: PipelineFacts,
    instance: str,
    urls: dict[str, str],
    discussion_url: str | None,
) -> str:
    """The Slack draft. Short, one link, one ask — it competes with a busy channel."""
    live, deep = dashboard_url(facts, instance, urls)
    if not deep:
        live = f'{live} (the "{project_tag(facts)}" project)'
    where = discussion_url or "<discussion URL once created>"
    tabs = ", ".join(t.title for t in facts.tabs if t.title)
    return (
        f"<!-- post in the nf-core Slack, #{facts.pipeline} -->\n\n"
        f"Hi :wave: We build Depictio, an open-source dashboard layer for pipeline output, "
        f"and we have put together a dashboard for nf-core/{facts.pipeline} {facts.version} "
        f"straight from the AWS megatest run.\n\n"
        f"It is live here, no login: {live}\n"
        f"Tabs: {tabs}\n\n"
        f"Before we call it done we would rather hear from the people who know this pipeline: "
        f"is anything on it wrong, what do you always look at that is missing, and which "
        f"parameter combinations would break it? Three questions, spelled out here: {where}\n\n"
        f"Any answer, however short, is worth more than none. Happy to demo it live if that "
        f"is easier.\n"
    )


def render_epic(
    all_facts: list[PipelineFacts],
    instance: str,
    docs_url_template: str,
    urls: dict[str, str],
    discussions: dict[str, str],
) -> str:
    """The tracking table for the round's epic issue. Regenerate and re-post as it moves."""
    rows = []
    for facts in all_facts:
        pr = facts.pr
        live, deep = dashboard_url(facts, instance, urls)
        docs = docs_url_template.format(pipeline=facts.pipeline, version=facts.version)
        rows.append(
            [
                f"nf-core/{facts.pipeline}",
                facts.version,
                f"#{pr['number']}" if pr else "—",
                f"[dashboard]({live})" if deep else "⚠ needs link",
                f"[docs]({docs})",
                f"[thread]({discussions[facts.pipeline]})"
                if facts.pipeline in discussions
                else "—",
                "☐",
                "☐",
            ]
        )
    body = [
        "## nf-core template review round\n\n",
        "One discussion per pipeline, each asking its maintainers the same three questions: "
        "is anything wrong, what is missing, which runs would it not fit. This table is "
        "generated by `scripts/nfcore_outreach.py` — regenerate it rather than editing cells.\n\n",
        _md_table(
            ["Pipeline", "Version", "PR", "Live", "Docs", "Thread", "Contacted", "Answered"],
            rows,
        ),
        "\n### How a reply gets handled\n\n",
        "1. Anything concrete becomes an issue linked back to the thread.\n"
        "2. Anything that changes a panel goes into the template YAML, and the docs page "
        "is regenerated from it.\n"
        "3. The thread is answered either way, so nobody wonders whether it landed.\n",
    ]
    return "".join(body)


# ---------------------------------------------------------------------------
# Publishing (opt-in)
# ---------------------------------------------------------------------------
def _gh_graphql(query: str, **variables: str) -> dict:
    args = ["gh", "api", "graphql", "-f", f"query={query}"]
    for name, value in variables.items():
        args += ["-F", f"{name}={value}"]
    raw = subprocess.run(args, capture_output=True, text=True, check=True, timeout=60).stdout
    payload = json.loads(raw or "{}")
    if payload.get("errors"):
        raise RuntimeError(payload["errors"])
    return payload.get("data", {})


_REPO_QUERY = """
query($owner:String!,$name:String!){
  repository(owner:$owner,name:$name){
    id
    discussionCategories(first:50){nodes{id name}}
    discussions(first:100,orderBy:{field:CREATED_AT,direction:DESC}){nodes{title url}}
  }
}
"""

_CREATE_MUTATION = """
mutation($repo:ID!,$category:ID!,$title:String!,$body:String!){
  createDiscussion(input:{repositoryId:$repo,categoryId:$category,title:$title,body:$body}){
    discussion{url}
  }
}
"""


def create_discussions(
    bundles: list[tuple[PipelineFacts, str, str]],
    repo: str,
    category_name: str,
) -> dict[str, str]:
    """Post one discussion per pipeline, skipping titles that already exist.

    Returns pipeline -> URL for everything that now has a thread, created here
    or found already posted, so the epic table is complete either way.
    """
    if shutil.which("gh") is None:
        raise SystemExit("gh is not on PATH — cannot create discussions")
    owner, name = repo.split("/", 1)
    data = _gh_graphql(_REPO_QUERY, owner=owner, name=name)["repository"]
    categories = {c["name"]: c["id"] for c in data["discussionCategories"]["nodes"]}
    if category_name not in categories:
        raise SystemExit(
            f"No discussion category named {category_name!r} in {repo}. "
            f"Have: {', '.join(sorted(categories)) or '(none)'}. Create it in the repo settings."
        )
    existing = {d["title"]: d["url"] for d in data["discussions"]["nodes"]}

    urls: dict[str, str] = {}
    for facts, title, body in bundles:
        if title in existing:
            print(f"  = {facts.pipeline}: already posted ({existing[title]})", file=sys.stderr)
            urls[facts.pipeline] = existing[title]
            continue
        created = _gh_graphql(
            _CREATE_MUTATION,
            repo=data["id"],
            category=categories[category_name],
            title=title,
            body=body,
        )
        url = created["createDiscussion"]["discussion"]["url"]
        print(f"  + {facts.pipeline}: {url}", file=sys.stderr)
        urls[facts.pipeline] = url
    return urls


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------
def discussion_title(facts: PipelineFacts) -> str:
    """Stable across re-runs — it is what makes `--create-discussions` idempotent."""
    return f"[{facts.pipeline}] Depictio dashboard for nf-core/{facts.pipeline} {facts.version}: does it look right to you?"


def cmd_outreach(args: argparse.Namespace) -> int:
    projects_dir = Path(args.projects_dir) if args.projects_dir else NFCORE_PROJECTS_DIR
    available = discover_pipelines(projects_dir)
    if not available:
        print(f"No templated pipelines under {projects_dir}", file=sys.stderr)
        return 2

    wanted = args.pipeline or sorted(available)
    unknown = [p for p in wanted if p not in available]
    if unknown:
        print(
            f"Unknown pipeline(s): {', '.join(unknown)} (have: {', '.join(sorted(available))})",
            file=sys.stderr,
        )
        return 2

    prs = {} if args.no_pr_lookup else fetch_pull_requests(args.repo)

    all_facts: list[PipelineFacts] = []
    for pipeline in wanted:
        version = str(local_latest_version(available[pipeline]))
        facts = collect_facts(pipeline, version, projects_dir=projects_dir)
        facts.pr = prs.get(pipeline)
        all_facts.append(facts)
        print(
            f"→ {pipeline} {version}: {len(facts.tabs)} tab(s), "
            f"{len(facts.data_collections)} data collection(s), "
            f"{len(facts.screenshots)} screenshot(s)"
            f"{'' if facts.pr else ', no PR found'}",
            file=sys.stderr,
        )

    if args.json:
        print(json.dumps([asdict(f) for f in all_facts], indent=2, default=str))
        return 0

    urls = load_dashboard_urls(args.dashboard_urls)
    missing = [f.pipeline for f in all_facts if f.pipeline not in urls]
    if missing:
        print(
            f"  ! no dashboard link for {', '.join(missing)} — those fall back to "
            f"{args.instance.rstrip('/')}/dashboards (pass --dashboard-urls to deep-link)",
            file=sys.stderr,
        )

    bundles = [
        (
            facts,
            discussion_title(facts),
            render_discussion(facts, args.instance, args.docs_url, urls),
        )
        for facts in all_facts
    ]

    discussions: dict[str, str] = {}
    if args.create_discussions:
        discussions = create_discussions(bundles, args.repo, args.category)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for facts, title, body in bundles:
        (out_dir / f"{facts.pipeline}.md").write_text(f"<!-- title: {title} -->\n\n{body}")
        (out_dir / f"{facts.pipeline}.slack.md").write_text(
            render_slack(facts, args.instance, urls, discussions.get(facts.pipeline))
        )
    (out_dir / "EPIC.md").write_text(
        render_epic(all_facts, args.instance, args.docs_url, urls, discussions)
    )
    (out_dir / "facts.json").write_text(
        json.dumps([asdict(f) for f in all_facts], indent=2, default=str)
    )

    print(f"\nWrote {len(bundles) * 2 + 2} files to {out_dir}", file=sys.stderr)
    if not args.create_discussions:
        print(
            "Nothing was posted. Review the bodies, then re-run with --create-discussions.",
            file=sys.stderr,
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--pipeline",
        action="append",
        help="Pipeline to prepare (repeatable; default: every templated pipeline)",
    )
    parser.add_argument(
        "--out-dir",
        default=str(DEFAULT_OUT_DIR),
        help=f"Where the bundles are written (default: {DEFAULT_OUT_DIR.relative_to(_REPO_ROOT)})",
    )
    parser.add_argument(
        "--instance",
        default=DEFAULT_INSTANCE,
        help=f"Depictio instance the dashboards are served from (default: {DEFAULT_INSTANCE})",
    )
    parser.add_argument(
        "--docs-url",
        default=DEFAULT_DOCS_URL,
        help="Docs URL template; {pipeline} and {version} are substituted",
    )
    parser.add_argument(
        "--dashboard-urls",
        help="JSON file mapping pipeline -> live dashboard URL, so the bundles deep-link "
        "instead of pointing at the instance's dashboard list",
    )
    parser.add_argument(
        "--repo", default=DEFAULT_REPO, help=f"GitHub repo (default: {DEFAULT_REPO})"
    )
    parser.add_argument(
        "--category",
        default=DEFAULT_CATEGORY,
        help=f"Discussion category to post into (default: {DEFAULT_CATEGORY!r})",
    )
    parser.add_argument(
        "--projects-dir", help="Override the nf-core template root (mostly for tests)"
    )
    parser.add_argument(
        "--no-pr-lookup", action="store_true", help="Skip the gh PR lookup (offline runs)"
    )
    parser.add_argument(
        "--json", action="store_true", help="Print the collected facts and write nothing"
    )
    parser.add_argument(
        "--create-discussions",
        action="store_true",
        help="Actually post the discussions (idempotent by title). Off by default.",
    )
    parser.set_defaults(func=cmd_outreach)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
