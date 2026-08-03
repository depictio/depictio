/**
 * Non-live components must carry an always-visible tier badge (RFC §3.2:
 * "never dropped, never silently wrong") — pinned, not hover-revealed.
 */
import { expect, test } from "@playwright/test";

import { blockNetwork, injectedBundleUrl, skipUnlessBundleBuilt } from "./helpers";

test.beforeEach(() => skipUnlessBundleBuilt());

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

  // Badge tooltip surfaces the manifest's `detail` string.
  await badges.first().hover();
  await expect(page.getByText("phase 0: all tiers frozen").first()).toBeVisible();
});
