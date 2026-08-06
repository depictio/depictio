/**
 * Non-live components must carry an always-visible tier badge (RFC §3.2:
 * "never dropped, never silently wrong") — pinned, not hover-revealed — and
 * the badge must EXPLAIN itself in product language.
 *
 * The producers write `detail` for whoever debugs an export: it names RFC
 * sections, roadmap phases, and (when a payload fails) the raw exception. So
 * the hover card leads with the curated sentence for the tier + reason, and
 * only offers `detail` behind "Technical details" when it reads as prose. The
 * basic fixture's detail ("phase 0: all tiers frozen") is exactly the kind
 * that must not reach a reader.
 */
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

import {
  FIXTURE_MANIFEST,
  blockNetwork,
  injectedBundleUrl,
  skipUnlessBundleBuilt,
} from "./helpers";

test.beforeEach(() => skipUnlessBundleBuilt());

/** The basic fixture with `mutate` applied, written where the injector can
 *  read it. Lets one test bend the manifest without a committed fixture. */
function variantManifest(mutate: (manifest: any) => void): string {
  const manifest = JSON.parse(readFileSync(FIXTURE_MANIFEST, "utf-8"));
  mutate(manifest);
  const out = join(mkdtempSync(join(tmpdir(), "depictio-badge-")), "manifest.json");
  writeFileSync(out, JSON.stringify(manifest));
  return out;
}

test("every frozen component shows a pinned badge; live components show none", async ({
  page,
}) => {
  await blockNetwork(page);
  await page.goto(injectedBundleUrl());
  await expect(page.locator(".react-grid-item")).toHaveCount(3);

  // Fixture: card + figure + interactive are frozen, text is live.
  const badges = page.locator("[data-static-tier]");
  await expect(badges).toHaveCount(3);
  for (const badge of await badges.all()) {
    await expect(badge).toHaveAttribute("data-static-tier", "frozen");
    // Visible without hovering anything.
    await expect(badge).toBeVisible();
  }

  // The live text component's chrome carries no badge.
  const textItem = page
    .locator(".depictio-component-chrome")
    .filter({ hasText: "A hand-written fixture manifest" });
  await expect(textItem.locator("[data-static-tier]")).toHaveCount(0);
});

test("a frozen badge explains the tier in product language, not build prose", async ({
  page,
}) => {
  await blockNetwork(page);
  await page.goto(injectedBundleUrl());
  const badge = page.locator("[data-static-tier]").first();

  await badge.hover();
  const card = page.locator(".mantine-HoverCard-dropdown");
  await expect(card).toBeVisible();
  // Headline (what the tier means) + the curated sentence for the reason.
  await expect(card).toContainText("Filters do not affect this view");
  await expect(card).toContainText(
    "This view cannot be rebuilt in your browser",
  );
  // The fixture's build note names an internal phase, so it is not offered at
  // all — neither as text nor behind the toggle.
  await expect(card).not.toContainText("phase 0");
  await expect(
    card.locator("[data-testid='static-tier-detail-toggle']"),
  ).toHaveCount(0);
});

test("a component the viewer cannot draw is still badged", async ({ page }) => {
  // Two components of a type no renderer handles: one classified omitted by
  // the manifest, one the manifest never classified at all. Both used to fall
  // through the renderer's last-resort branch, which rendered OUTSIDE the
  // chrome — so the tiles a bundle degraded hardest were the only ones with
  // nothing saying why.
  const manifestPath = variantManifest((manifest) => {
    manifest.dashboard.doc.stored_metadata.push(
      { index: "comp-exotic-1", component_type: "hologram", title: "Exotic", order: 4 },
      { index: "comp-untiered-1", component_type: "hologram", title: "Untiered", order: 5 },
    );
    manifest.tiers["comp-exotic-1"] = {
      tier: "omitted",
      reason: "unsupported",
      detail: null,
    };
    // comp-untiered-1 is deliberately left out of `tiers`.
  });

  await blockNetwork(page);
  await page.goto(injectedBundleUrl(manifestPath));
  await expect(page.getByText("not yet ported")).toHaveCount(2);

  const omitted = page.locator('[data-static-tier="omitted"]');
  await expect(omitted).toHaveText("Omitted");
  await omitted.hover();
  await expect(page.locator(".mantine-HoverCard-dropdown")).toContainText(
    "This view could not be built for the export",
  );

  // No verdict in the manifest is not the same as a clean bill of health.
  const unverified = page.locator('[data-static-tier="unknown"]');
  await expect(unverified).toHaveText("Unverified");
});
