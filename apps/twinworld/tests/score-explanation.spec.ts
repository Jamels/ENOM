import { test, expect } from "@playwright/test";

test("expanding an Earth candidate exposes the evidence behind its score", async ({ page }) => {
  await page.goto("/");
  const panel = page.getByRole("region", { name: "Eight dimension discovery" });
  const topCandidate = panel.locator("summary").filter({ hasText: /^#1 / }).first();
  await expect(topCandidate).toBeVisible();
  await topCandidate.click();
  const candidate = topCandidate.locator("..");
  const terrain = candidate.locator("details").filter({ has: page.locator("summary").filter({ hasText: /Terrain & surface hazards/ }) }).first();
  await terrain.locator("summary").first().click();
  await expect(terrain.locator("p").filter({ hasText: /^Assigned weight/ })).toContainText("effective weight");
  await expect(terrain.getByText(/Weighted score contribution .*before normalization/)).toBeVisible();
  await expect(terrain.getByText(/target .* → Earth .*component/i).first()).toBeVisible();
});
