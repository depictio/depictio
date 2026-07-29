#!/usr/bin/env python3
"""Does Restore work from the drawer, in a browser, on the real stack?

Everything else here is checked through the API. Restore is the operation the
whole feature exists for, and it is the one that only happens through the UI: a
click on a timeline row's menu, a confirmation, and a grid that has to redraw
into a different shape.

That last part is the reason this is a browser check rather than another API
call. A restore that writes the right document and leaves the grid showing the
old one is indistinguishable from a working restore in any API assertion, and it
has been the failure mode twice in this branch's history (a figure that redrew
only after a page reload; a component that kept a stale render key).

Restores `v1 Survey` (5 components) from whatever is current (9), asserts the
grid actually shrinks, then restores the state it started from — which is only
possible because a restore captures the pre-restore state first, so this check
also exercises that guarantee rather than asserting it.

    uv run python check_restore_in_browser.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import yaml
from playwright.async_api import Page, async_playwright

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from depictio.api.v1.services.screenshot_helpers import (  # noqa: E402
    build_localstorage_init_script,
)

ADMIN_CONFIG = REPO_ROOT / "depictio" / ".depictio" / "admin_config.yaml"
TARGET_LABEL = "v1 Survey"
TARGET_COMPONENTS = 5


def token_payload() -> str:
    """The `local-store` blob the SPA expects, from the local admin config."""
    info = yaml.safe_load(ADMIN_CONFIG.read_text())["user"]["token"]
    payload = {
        "_id": str(info.get("id")),
        "user_id": str(info.get("user_id")),
        "logged_in": True,
        "expire_datetime": info.get("expire_datetime"),
        "created_at": info.get("created_at"),
        "refresh_expire_datetime": info.get("refresh_expire_datetime"),
        "access_token": info.get("access_token"),
        "refresh_token": info.get("refresh_token"),
        "name": info.get("name"),
        "token_lifetime": info.get("token_lifetime"),
        "token_type": info.get("token_type"),
    }
    return json.dumps({k: v for k, v in payload.items() if v is not None})


async def open_drawer(page: Page, viewer: str, dashboard: str) -> None:
    await page.goto(f"{viewer}/dashboard-edit/{dashboard}", wait_until="domcontentloaded")
    await page.wait_for_timeout(6_000)
    await page.get_by_role("button", name="Settings").click()
    await page.get_by_test_id("open-version-history").click()
    # `data-testid` sits on the Drawer root, which stays visibility:hidden.
    await page.locator(".mantine-Drawer-content").last.wait_for(state="visible", timeout=15_000)
    await page.wait_for_timeout(1_800)


async def restore_labelled(page: Page, label: str) -> None:
    """Open the menu on the row carrying `label` and confirm its Restore."""
    row = page.get_by_test_id("version-timeline-item").filter(has_text=label).first
    await row.wait_for(state="visible", timeout=15_000)
    await row.get_by_test_id("version-actions").click()
    await page.locator(".mantine-Menu-dropdown").first.wait_for(state="visible", timeout=10_000)
    await page.get_by_test_id("version-restore").click()
    # A second, explicit confirmation — the drawer never restores on one click.
    await page.get_by_test_id("version-restore-confirm").click(timeout=15_000)
    await page.wait_for_timeout(9_000)


async def grid_count(page: Page) -> int:
    return await page.locator(".react-grid-item").count()


async def run(viewer: str, dashboard: str, headless: bool) -> int:
    failures: list[str] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(viewport={"width": 1440, "height": 900})
        await context.add_init_script(build_localstorage_init_script(token_payload(), "light"))
        page = await context.new_page()

        await open_drawer(page, viewer, dashboard)
        before = await grid_count(page)
        print(f"grid before restore: {before} components")
        if before == TARGET_COMPONENTS:
            print(
                f"  ! already at {TARGET_COMPONENTS} components — this check needs the demo "
                "in its rebuilt state to be meaningful"
            )

        print(f"restoring {TARGET_LABEL!r} ...")
        await restore_labelled(page, TARGET_LABEL)

        after = await grid_count(page)
        print(f"grid after restore:  {after} components")
        if after != TARGET_COMPONENTS:
            failures.append(
                f"the grid shows {after} components, not {TARGET_COMPONENTS} — "
                "the restore did not reach the screen without a reload"
            )
        else:
            print(f"  the grid redrew to {TARGET_COMPONENTS} components, no reload needed")

        # Undo it. Only possible because a restore captures the pre-restore state
        # first, so this is that guarantee exercised rather than asserted.
        await open_drawer(page, viewer, dashboard)
        rows = page.get_by_test_id("version-timeline-item")
        restored_back = False
        for index in range(await rows.count()):
            row = rows.nth(index)
            text = await row.inner_text()
            if f"{before} components" in text:
                await row.get_by_test_id("version-actions").click()
                await page.locator(".mantine-Menu-dropdown").first.wait_for(
                    state="visible", timeout=10_000
                )
                await page.get_by_test_id("version-restore").click()
                await page.get_by_test_id("version-restore-confirm").click(timeout=15_000)
                await page.wait_for_timeout(9_000)
                restored_back = True
                break

        if not restored_back:
            failures.append(
                f"no version holds the pre-restore state ({before} components) — "
                "a restore must capture what it replaced"
            )
        else:
            final = await grid_count(page)
            print(f"grid after undo:     {final} components")
            if final != before:
                failures.append(f"undo landed on {final} components, expected {before}")
            else:
                print("  the restore was itself undoable")

        await browser.close()

    print()
    if failures:
        print("FAILED:")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("OK: restore reaches the screen, and is itself undoable")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--viewer-url", default="http://localhost:5600")
    parser.add_argument("--dashboard-id", default="6a6a6d1e56f07a2b61f51c4e")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    return asyncio.run(run(args.viewer_url, args.dashboard_id, not args.headed))


if __name__ == "__main__":
    sys.exit(main())
