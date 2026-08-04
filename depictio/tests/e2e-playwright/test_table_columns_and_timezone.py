"""Browser-level checks of the dashboard/project tables (issue #932).

Drives the real `DashboardTableView` / `ProjectTableView` React components in
headless Chromium, via the dev-only `table-harness.html`, under a CEST
timezone. This covers what typechecking cannot: that timestamps actually
render shifted into the viewer's zone, and that the column picker really
shows/hides columns and persists the choice across a reload.

Skipped unless the harness dev server is running:
    cd depictio/viewer && npx vite --config vite.table-harness.config.ts
"""

import urllib.error
import urllib.request

import pytest

HARNESS_URL = "http://localhost:5199/table-harness.html"
# The fixture rows use 09:00 UTC, which is 11:00 in CEST (UTC+2).
VIEWER_TZ = "Europe/Berlin"


def _harness_running() -> bool:
    try:
        with urllib.request.urlopen(HARNESS_URL, timeout=2) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


pytestmark = pytest.mark.skipif(
    not _harness_running(),
    reason=(
        "table harness not running; start with: cd depictio/viewer && "
        "npx vite --config vite.table-harness.config.ts"
    ),
)


@pytest.fixture(scope="module")
def page_factory():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()

        def _new_page(context=None):
            ctx = context or browser.new_context(timezone_id=VIEWER_TZ)
            page = ctx.new_page()
            page.goto(HARNESS_URL)
            page.wait_for_selector("table")
            return page, ctx

        yield _new_page
        browser.close()


def _toggle_column(page, label: str) -> None:
    """Toggle a column the way a user does: click its label in the picker.

    Deliberately clicks the checkbox's own label rather than the surrounding
    menu row — that is the natural target, and it caught a double-toggle where
    the Checkbox's onChange and Menu.Item's onClick cancelled each other out.
    """
    page.locator('[aria-label="Choose columns"]').first.click()
    page.get_by_text(label, exact=True).last.click()
    page.keyboard.press("Escape")


def _column_headers(page) -> list[str]:
    """Visible header labels of the first (dashboards) table."""
    headers = page.locator("table").first.locator("thead th").all_inner_texts()
    return [h.strip() for h in headers if h.strip()]


class TestTimezoneRendering:
    def test_utc_timestamp_renders_in_the_viewers_timezone(self, page_factory):
        """09:00 UTC must show as 11:00 for a CEST viewer, not 09:00."""
        page, ctx = page_factory()
        try:
            body = page.locator("table").first.inner_text()
            assert "2026-08-04 11:00" in body, (
                f"expected the CEST-shifted time in the table, got:\n{body}"
            )
            assert "2026-08-04 09:00" not in body, "raw UTC leaked into the cell"
        finally:
            ctx.close()

    def test_same_instant_renders_as_utc_for_a_utc_viewer(self, page_factory):
        """The same data in UTC must render unshifted — proves it's not a constant offset."""
        from playwright.sync_api import sync_playwright  # noqa: F401

        page, ctx = page_factory()
        try:
            utc_ctx = ctx.browser.new_context(timezone_id="UTC")
            utc_page = utc_ctx.new_page()
            utc_page.goto(HARNESS_URL)
            utc_page.wait_for_selector("table")
            body = utc_page.locator("table").first.inner_text()
            assert "2026-08-04 09:00" in body
            utc_ctx.close()
        finally:
            ctx.close()

    def test_missing_timestamp_renders_a_placeholder_not_epoch(self, page_factory):
        """An empty `last_saved_ts` must not become 1970."""
        page, ctx = page_factory()
        try:
            body = page.locator("table").first.inner_text()
            assert "1970" not in body
            assert "Invalid Date" not in body
            assert "Never" in body
        finally:
            ctx.close()


class TestColumnPicker:
    def test_default_columns_include_created_and_modified(self, page_factory):
        page, ctx = page_factory()
        try:
            headers = _column_headers(page)
            assert "Created" in headers
            assert "Modified" in headers
        finally:
            ctx.close()

    def test_optional_columns_are_hidden_by_default(self, page_factory):
        """Extra metadata is opt-in so the default table stays readable."""
        page, ctx = page_factory()
        try:
            headers = _column_headers(page)
            assert "Version" not in headers
            assert "Subtitle" not in headers
        finally:
            ctx.close()

    def test_toggling_a_column_adds_it_to_the_table(self, page_factory):
        page, ctx = page_factory()
        try:
            assert "Version" not in _column_headers(page)

            _toggle_column(page, "Version")

            assert "Version" in _column_headers(page), "column did not appear after toggling on"
        finally:
            ctx.close()

    def test_column_choice_persists_across_a_reload(self, page_factory):
        """The selection is stored in localStorage, so it must survive F5."""
        page, ctx = page_factory()
        try:
            _toggle_column(page, "Version")
            assert "Version" in _column_headers(page)

            page.reload()
            page.wait_for_selector("table")
            assert "Version" in _column_headers(page), "selection was lost on reload"
        finally:
            ctx.close()

    def test_always_visible_column_cannot_be_hidden(self, page_factory):
        """Hiding Title would leave rows with no way to identify them."""
        page, ctx = page_factory()
        try:
            page.locator('[aria-label="Choose columns"]').first.click()
            checkbox = page.locator('input[type="checkbox"]:disabled').first
            assert checkbox.is_checked(), "Title must stay checked and disabled"
            page.keyboard.press("Escape")
            assert "Title" in _column_headers(page)
        finally:
            ctx.close()
