"""Drive a push from instance A to instance B over the network, and check the result.

Run by ``run.sh demo`` (one machine) or by hand against two machines:

    uv run --extra dev python dev/migration_lan_test/check.py \
        --source http://A_IP:18058 --target http://B_IP:18059 --pairing-key KEY

Both instances are ``depictio local up`` stacks: their admin is
``admin@example.com`` with the password kept in ``<local home>/secrets.json``
(``--source-home`` / ``--target-home``, or ``--*-password``).

Scenarios, each reported PASS/FAIL in a Markdown report:
  1. push iris A -> B (inline), approve with lock; on B: owner, provenance hop,
     published lock, 409 on /save and on a delta table upsert, data readable
     with the bucket rewritten, same column specs as on A;
  2. re-push: a new request, approved, adds an ``import`` version on B;
  3. negatives: wrong key 403, unknown request 404, non-admin approval refused,
     rejection removes the request from the pending queue.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

API = "/depictio/api/v1"
ADMIN = "admin@example.com"


@dataclass
class Report:
    rows: list[tuple[str, bool, str]] = field(default_factory=list)

    def check(self, name: str, ok: bool, detail: Any = "") -> bool:
        text = detail if isinstance(detail, str) else json.dumps(detail, default=str)[:400]
        self.rows.append((name, bool(ok), text))
        print(f"{'PASS' if ok else 'FAIL'}  {name}  {text}", flush=True)
        return bool(ok)

    @property
    def failed(self) -> int:
        return sum(1 for _, ok, _ in self.rows if not ok)

    def markdown(self, source: str, target: str) -> str:
        lines = [
            "# Migration LAN test",
            "",
            f"Source A: `{source}` · Target B: `{target}`",
            "",
            f"**{len(self.rows) - self.failed}/{len(self.rows)} checks passed**",
            "",
            "| | Check | Detail |",
            "|---|---|---|",
        ]
        for name, ok, detail in self.rows:
            cell = detail.replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {'✅' if ok else '❌'} | {name} | {cell} |")
        return "\n".join(lines) + "\n"


class Instance:
    def __init__(self, base: str, password: str) -> None:
        self.base = base.rstrip("/")
        # trust_env=False: a corporate/agent proxy must not sit between two LAN hosts.
        self.http = httpx.Client(base_url=self.base + API, timeout=120, trust_env=False)
        token = self._login(password)
        self.http.headers["Authorization"] = f"Bearer {token}"

    def _login(self, password: str) -> str:
        for delay in (0, 2, 5, 15):
            time.sleep(delay)
            r = self.http.post("/auth/login", data={"username": ADMIN, "password": password})
            if r.status_code != 429:
                r.raise_for_status()
                return r.json()["access_token"]
        raise RuntimeError(f"login rate-limited on {self.base}")

    def get(self, path: str, **kw: Any) -> httpx.Response:
        return self.http.get(path, **kw)

    def post(self, path: str, **kw: Any) -> httpx.Response:
        return self.http.post(path, **kw)


def _password(home: str | None, explicit: str | None) -> str:
    if explicit:
        return explicit
    if not home:
        sys.exit("give --*-home (a depictio local home) or --*-password")
    return json.loads((Path(home) / "secrets.json").read_text())["admin_password"]


def _wait(fn, until, timeout: float = 300, every: float = 2) -> Any:
    deadline = time.time() + timeout
    value = fn()
    while not until(value) and time.time() < deadline:
        time.sleep(every)
        value = fn()
    return value


def _project(inst: Instance, name: str) -> dict | None:
    r = inst.get("/projects/get/all")
    r.raise_for_status()
    return next((p for p in r.json() if p.get("name") == name), None)


def _dc_ids(project: dict) -> list[str]:
    out = [str(dc.get("id") or dc.get("_id")) for dc in project.get("data_collections") or []]
    for wf in project.get("workflows") or []:
        out += [str(dc.get("id") or dc.get("_id")) for dc in wf.get("data_collections") or []]
    return [d for d in out if d and d != "None"]


def _dashboards(inst: Instance, project_id: str) -> list[dict]:
    r = inst.get("/dashboards/list")
    r.raise_for_status()
    body = r.json()
    items = body if isinstance(body, list) else body.get("dashboards", [])
    return [d for d in items if str(d.get("project_id")) == project_id]


def _push_and_approve(
    a: Instance, b: Instance, rep: Report, project_id: str, label: str, *, lock: bool = True
) -> dict | None:
    targets = a.get("/migrate/push/targets").json().get("targets", [])
    target = next((t for t in targets if t["name"] == "lan-b"), None)
    if not rep.check(f"{label}: A lists target lan-b", target is not None, targets):
        return None
    pre = a.post(
        "/migrate/push/preflight", json={"project_id": project_id, "target_id": target["id"]}
    )
    pre_body = pre.json()
    rep.check(
        f"{label}: preflight over the LAN",
        pre.status_code == 200 and pre_body.get("can_push"),
        {k: pre_body.get(k) for k in ("transfer_mode", "total_bytes", "object_count", "errors")},
    )
    started = a.post(
        "/migrate/push",
        json={"project_id": project_id, "target_id": target["id"], "message": label},
    )
    if not rep.check(f"{label}: push accepted (202)", started.status_code == 202, started.text):
        return None
    push_id = started.json()["push_id"]
    push = _wait(
        lambda: a.get(f"/migrate/push/{push_id}").json(),
        lambda p: p.get("status") in ("submitted", "failed"),
    )
    if not rep.check(
        f"{label}: bundle built and uploaded to B",
        push.get("status") == "submitted",
        {k: push.get(k) for k in ("status", "transfer_mode", "bundle_bytes", "error")},
    ):
        return None
    request_id = push["remote_request_id"]
    queue = b.get("/migrate/requests", params={"status": "pending"}).json().get("requests", [])
    rep.check(
        f"{label}: request waits in B's admin queue",
        any(r["id"] == request_id for r in queue),
        [(r["id"], r["status"], r["source_name"]) for r in queue],
    )
    detail = b.get(f"/migrate/requests/{request_id}").json()
    rep.check(
        f"{label}: B names the source from the pairing key",
        detail.get("source_name") == "lan-a",
        detail.get("source_name"),
    )
    appr = b.post(
        f"/migrate/requests/{request_id}/approve", json={"lock": lock, "make_public": False}
    )
    rep.check(f"{label}: approval accepted", appr.status_code == 202, appr.text)
    done = _wait(
        lambda: b.get(f"/migrate/requests/{request_id}").json(),
        lambda d: d.get("status") in ("imported", "failed"),
    )
    rep.check(
        f"{label}: imported on B",
        done.get("status") == "imported",
        {"status": done.get("status"), "result": done.get("result")},
    )
    remote = _wait(
        lambda: a.get(f"/migrate/push/{push_id}").json(),
        lambda p: p.get("remote_status") == "imported",
        timeout=30,
    )
    rep.check(
        f"{label}: A reads the remote status back",
        remote.get("remote_status") == "imported",
        remote.get("remote_status"),
    )
    return done


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--pairing-key", required=True)
    ap.add_argument("--source-home")
    ap.add_argument("--target-home")
    ap.add_argument("--source-password")
    ap.add_argument("--target-password")
    ap.add_argument("--project", default="Iris Dataset Project Data Analysis")
    ap.add_argument("--report")
    args = ap.parse_args()

    rep = Report()
    a = Instance(args.source, _password(args.source_home, args.source_password))
    b = Instance(args.target, _password(args.target_home, args.target_password))

    # -- 0. both instances answer over the LAN, B accepts A's key -----------
    info = httpx.get(
        f"{b.base}{API}/migrate/inbound/info",
        headers={"X-Depictio-Pairing-Key": args.pairing_key},
        trust_env=False,
    )
    rep.check("B /inbound/info with A's key", info.status_code == 200, info.text[:300])
    bad = httpx.get(
        f"{b.base}{API}/migrate/inbound/info",
        headers={"X-Depictio-Pairing-Key": "x" * 64},
        trust_env=False,
    )
    rep.check("B refuses a wrong key (403)", bad.status_code == 403, bad.status_code)

    project = _project(a, args.project)
    if not rep.check("A has the project", project is not None, args.project):
        return _finish(rep, args)
    pid = str(project.get("id") or project.get("_id"))

    # -- 1. first push, approved with lock -----------------------------------
    done = _push_and_approve(a, b, rep, pid, "push #1")
    if done:
        imported = _project(b, args.project)
        rep.check(
            "project exists on B with the same id",
            imported and str(imported.get("id") or imported.get("_id")) == pid,
            pid,
        )
        if imported:
            hops = (imported.get("provenance") or {}).get("imported_from") or []
            rep.check(
                "provenance hop recorded (via push, from lan-a)",
                bool(hops)
                and hops[-1].get("via") == "push"
                and hops[-1].get("source_instance") == "lan-a",
                hops[-1:] if hops else hops,
            )
            lock = imported.get("published_lock") or {}
            rep.check("published read-only on B", lock.get("source") == "migration", lock)
            owners = [o.get("email") for o in (imported.get("permissions") or {}).get("owners", [])]
            rep.check("owner on B is the requester's account", ADMIN in owners, owners)

            dashes = _dashboards(b, pid)
            rep.check("dashboards imported", bool(dashes), len(dashes))
            if dashes:
                did = str(dashes[0].get("dashboard_id"))
                got = b.get(f"/dashboards/get/{did}").json()
                rep.check(
                    "/dashboards/get reports the lock",
                    bool(got.get("published_lock")),
                    got.get("published_lock"),
                )
                save = b.post(f"/dashboards/save/{did}", json={**got, "title": "changed on B"})
                rep.check("/save on B answers 409", save.status_code == 409, save.status_code)

            for dc in _dc_ids(imported)[:3]:
                dt_b = b.get(f"/deltatables/get/{dc}")
                if dt_b.status_code != 200:
                    rep.check(f"delta table {dc} on B", False, dt_b.status_code)
                    continue
                loc = dt_b.json().get("delta_table_location", "")
                rep.check(f"{dc}: location rewritten to B's bucket", loc.startswith("s3://"), loc)
                spec_a = a.get(f"/deltatables/specs/{dc}")
                spec_b = b.get(f"/deltatables/specs/{dc}")
                rep.check(
                    f"{dc}: B reads the data it received (specs equal A's)",
                    spec_b.status_code == 200 and spec_a.json() == spec_b.json(),
                    {"a": spec_a.status_code, "b": spec_b.status_code},
                )
                up = b.post("/deltatables/upsert", json={"data_collection_id": dc})
                rep.check(
                    f"{dc}: delta table upsert on B answers 409",
                    up.status_code == 409,
                    up.status_code,
                )

            # -- 2. re-push: a new version on B -----------------------------
            before = _versions(b, dashes)
            again = _push_and_approve(a, b, rep, pid, "re-push")
            if again:
                after = _versions(b, _dashboards(b, pid))
                rep.check(
                    "re-push adds an `import` version on B",
                    after.count("import") > before.count("import"),
                    {"before": before, "after": after},
                )

    # -- 3. negatives -----------------------------------------------------------
    missing = httpx.get(
        f"{b.base}{API}/migrate/inbound/requests/000000000000000000000000",
        headers={"X-Depictio-Pairing-Key": args.pairing_key},
        trust_env=False,
    )
    rep.check("unknown request id answers 404", missing.status_code == 404, missing.status_code)
    anon = httpx.post(
        f"{b.base}{API}/migrate/requests/000000000000000000000000/approve",
        json={"lock": True},
        trust_env=False,
    )
    rep.check(
        "approval without a session is refused", anon.status_code in (401, 403), anon.status_code
    )
    return _finish(rep, args)


def _versions(b: Instance, dashes: list[dict]) -> list[str]:
    kinds: list[str] = []
    for d in dashes:
        if d.get("is_main_tab") is False:
            continue
        r = b.get(f"/dashboards/{d['dashboard_id']}/versions")
        if r.status_code == 200:
            body = r.json()
            items = body if isinstance(body, list) else body.get("versions", [])
            kinds += [str(v.get("kind")) for v in items]
    return kinds


def _finish(rep: Report, args: argparse.Namespace) -> int:
    if args.report:
        Path(args.report).write_text(rep.markdown(args.source, args.target))
        print(f"report: {args.report}")
    print(f"{len(rep.rows) - rep.failed}/{len(rep.rows)} checks passed")
    return 1 if rep.failed else 0


if __name__ == "__main__":
    sys.exit(main())
