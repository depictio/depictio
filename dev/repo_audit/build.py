#!/usr/bin/env python3
"""Build the weekly depictio repo-audit page.

Fetches issues, PRs and milestones via the `gh` CLI, runs a fixed set of
mechanical hygiene checks over them, and renders `template.html`.

The point of this script is that the *styling never drifts*: the design lives
in template.html, committed once, and every weekly run fills the same slots.
Nothing here makes a judgment call — anything requiring one goes in notes.md,
which gets injected into its own bounded slot.

Usage:
    python3 dev/repo_audit/build.py                 # -> dev/repo_audit/audit.html
    python3 dev/repo_audit/build.py --raw raw.json  # also dump what gh returned
"""

from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
VERSION_RE = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")
CLOSES_RE = re.compile(r"\b(?:closes?|fixes?|resolves?)\s+#(\d+)", re.I)


# --------------------------------------------------------------------------- #
# fetch
# --------------------------------------------------------------------------- #
def gh_json(path: str) -> list:
    """Call `gh api <path> --paginate` and return the parsed array.

    --paginate concatenates pages as separate JSON arrays when the response is
    an array, so we ask gh to merge them into one via --slurp.
    """
    proc = subprocess.run(
        ["gh", "api", path, "--paginate", "--slurp"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        sys.exit(f"gh api {path} failed:\n{proc.stderr}")
    pages = json.loads(proc.stdout)
    return [item for page in pages for item in page]


def fetch(repo: str) -> dict:
    return {
        "milestones": gh_json(f"repos/{repo}/milestones?state=all&per_page=100"),
        # This endpoint returns issues *and* PRs, with bodies — one call covers both.
        "items": gh_json(f"repos/{repo}/issues?state=open&per_page=100"),
    }


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def version_key(title: str) -> tuple:
    """Sort key from a leading version, ignoring any `v` prefix.

    Titles without a version sort last rather than crashing the sort.
    """
    m = VERSION_RE.match(title.strip())
    return (0, *map(int, m.groups())) if m else (1, 0, 0, 0)


def version_of(title: str) -> str | None:
    m = VERSION_RE.match(title.strip())
    return ".".join(m.groups()) if m else None


def is_pr(item: dict) -> bool:
    return "pull_request" in item


def labels_of(item: dict) -> list[str]:
    return [lbl["name"] for lbl in item.get("labels") or []]


def esc(text: str) -> str:
    return html.escape(str(text), quote=True)


def ref(repo: str, item: dict) -> str:
    """A linked #number that lands on the right issue/pull URL."""
    kind = "pull" if is_pr(item) else "issues"
    return (
        f'<a class="ref" href="https://github.com/{repo}/{kind}/{item["number"]}">'
        f'#{item["number"]}</a>'
    )


# --------------------------------------------------------------------------- #
# checks — every one of these is mechanical, no judgment
# --------------------------------------------------------------------------- #
def run_checks(repo: str, milestones: list, items: list) -> list[dict]:
    by_ms: dict[int, list] = {}
    for it in items:
        if it.get("milestone"):
            by_ms.setdefault(it["milestone"]["number"], []).append(it)

    epics = [i for i in items if "epic" in labels_of(i) and not is_pr(i)]
    open_ms = [m for m in milestones if m["state"] == "open"]
    alerts: list[dict] = []

    # A closed milestone still holding open work means the release was cut
    # before its scope finished, or something was filed against it afterwards.
    for m in milestones:
        if m["state"] == "closed" and by_ms.get(m["number"]):
            leftovers = " ".join(ref(repo, i) for i in by_ms[m["number"]])
            alerts.append(
                {
                    "level": "bad",
                    "title": f'Closed milestone "{esc(m["title"])}" still holds open work',
                    "body": f"{leftovers} — move them to the next release or reopen the milestone.",
                }
            )

    # The auto-epic workflow guarantees this for new milestones; older ones
    # predate it and have to be caught here.
    for m in open_ms:
        if not any(
            e.get("milestone") and e["milestone"]["number"] == m["number"] for e in epics
        ):
            alerts.append(
                {
                    "level": "warn",
                    "title": f'Milestone "{esc(m["title"])}" has no epic',
                    "body": "Every milestone should have one tracking epic.",
                }
            )

    # An epic whose title claims a version that belongs to a *different*
    # milestone is the drift that produced #842 and #844.
    ms_by_version = {version_of(m["title"]): m for m in milestones if version_of(m["title"])}
    for e in epics:
        claimed = version_of(re.sub(r"^\[Epic\]\s*", "", e["title"]))
        if not claimed:
            continue
        owner = ms_by_version.get(claimed)
        if owner and (not e.get("milestone") or e["milestone"]["number"] != owner["number"]):
            alerts.append(
                {
                    "level": "warn",
                    "title": f'Epic {ref(repo, e)} claims version {claimed}, which belongs to "{esc(owner["title"])}"',
                    "body": "Renumber the epic, or attach it to that milestone.",
                }
            )

    unassigned = [i for i in items if not i.get("assignees") and not is_pr(i)]
    if unassigned:
        alerts.append(
            {
                "level": "warn",
                "title": f"{len(unassigned)} open issue(s) with no assignee",
                "body": " ".join(ref(repo, i) for i in unassigned),
            }
        )

    # "Unscheduled" is only a meaningful query if it is labelled, not merely
    # milestone-less.
    unlabelled = [
        i
        for i in items
        if not is_pr(i) and not i.get("milestone") and "backlog" not in labels_of(i)
    ]
    if unlabelled:
        alerts.append(
            {
                "level": "warn",
                "title": f"{len(unlabelled)} open issue(s) with no milestone and no backlog label",
                "body": " ".join(ref(repo, i) for i in unlabelled),
            }
        )

    if not alerts:
        alerts.append(
            {"level": "good", "title": "No hygiene issues found", "body": "Everything checks out."}
        )
    return alerts


def confirmed_links(repo: str, items: list) -> list[str]:
    """PR -> issue links GitHub will action on merge (closing keyword present)."""
    rows = []
    for it in sorted((i for i in items if is_pr(i)), key=lambda x: -x["number"]):
        found = sorted({int(n) for n in CLOSES_RE.findall(it.get("body") or "")})
        if found:
            issues = " ".join(
                f'<a class="ref" href="https://github.com/{repo}/issues/{n}">#{n}</a>'
                for n in found
            )
            rows.append(
                f"<tr><td>{ref(repo, it)}</td><td>{issues}</td>"
                f'<td><span class="pill good">auto-closes on merge</span></td></tr>'
            )
    return rows


# --------------------------------------------------------------------------- #
# render
# --------------------------------------------------------------------------- #
def render(repo: str, data: dict, notes_html: str) -> str:
    milestones, items = data["milestones"], data["items"]
    open_ms = sorted(
        (m for m in milestones if m["state"] == "open"), key=lambda m: version_key(m["title"])
    )
    issues = [i for i in items if not is_pr(i)]
    prs = [i for i in items if is_pr(i)]
    backlog = [i for i in issues if "backlog" in labels_of(i)]

    by_ms: dict[int, list] = {}
    for it in items:
        if it.get("milestone"):
            by_ms.setdefault(it["milestone"]["number"], []).append(it)

    stats = [
        (len(open_ms), "Open milestones"),
        (len(issues), "Open issues"),
        (len(prs), "Open PRs"),
        (len(backlog), "In backlog"),
        (sum(len(by_ms.get(m["number"], [])) for m in open_ms), "Items scheduled"),
    ]
    stat_html = "".join(
        f'<div class="stat"><div class="n">{n}</div><div class="l">{esc(label)}</div></div>'
        for n, label in stats
    )

    alert_html = "".join(
        f'<div class="callout {a["level"]}"><strong>{a["title"]}</strong>{a["body"]}</div>'
        for a in run_checks(repo, milestones, items)
    )

    roadmap = []
    for m in open_ms:
        contents = by_ms.get(m["number"], [])
        refs = " ".join(ref(repo, i) for i in sorted(contents, key=lambda x: -x["number"]))
        roadmap.append(
            f'<div class="rcard"><span class="rver">{esc(version_of(m["title"]) or "—")}'
            f'<span class="n">#{m["number"]}</span></span><div>'
            f'<div class="rtitle"><a href="{m["html_url"]}">{esc(m["title"])}</a></div>'
            f'<div class="rmeta">{len(contents)} open · {refs or "nothing attached"}</div>'
            f'</div></div>'
        )

    backlog_rows = "".join(
        f"<tr><td>{ref(repo, i)}</td>"
        f'<td>{esc(re.sub(r"^\[[A-Za-z]+\]\s*", "", i["title"]))}</td>'
        f'<td>{esc(", ".join(n for n in labels_of(i) if n != "backlog"))}</td></tr>'
        for i in sorted(backlog, key=lambda x: -x["number"])
    )

    link_rows = "".join(confirmed_links(repo, items)) or (
        '<tr><td colspan="3">No PR declares a closing keyword.</td></tr>'
    )

    template = (HERE / "template.html").read_text()
    slots = {
        "REPO": esc(repo),
        "GENERATED_AT": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "STATS": stat_html,
        "ALERTS": alert_html,
        "ROADMAP": "".join(roadmap),
        "BACKLOG_ROWS": backlog_rows,
        "BACKLOG_COUNT": str(len(backlog)),
        "LINK_ROWS": link_rows,
        "NOTES": notes_html,
    }
    for key, value in slots.items():
        template = template.replace("{{" + key + "}}", value)
    return template


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="depictio/depictio")
    ap.add_argument("--out", type=Path, default=HERE / "audit.html")
    ap.add_argument("--raw", type=Path, help="also dump the raw gh payload here")
    ap.add_argument(
        "--notes",
        type=Path,
        default=HERE / "notes.md",
        help="optional commentary injected into the Notes slot",
    )
    args = ap.parse_args()

    data = fetch(args.repo)
    if args.raw:
        args.raw.write_text(json.dumps(data, indent=2))

    if args.notes.exists() and args.notes.read_text().strip():
        # Deliberately minimal: paragraphs and links only. The template owns
        # every other visual decision so a week's notes cannot restyle the page.
        body = args.notes.read_text().strip()
        body = re.sub(r"#(\d+)", rf'<a class="ref" href="https://github.com/{args.repo}/issues/\1">#\1</a>', body)
        notes_html = "".join(f"<p>{line}</p>" for line in body.split("\n\n") if line.strip())
    else:
        notes_html = '<p class="empty">No commentary this week.</p>'

    args.out.write_text(render(args.repo, data, notes_html))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
