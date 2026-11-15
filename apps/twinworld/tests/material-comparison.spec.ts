import { expect, test } from "@playwright/test";

test("mapped material comparison shows groups and source context", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("tab", { name: "Moon", exact: true }).click();
  const target = page.locator("aside").first().getByRole("button", { name: /Mare Tranquillitatis Pit.*DEM/i });
  await target.click();
  const panel = page.getByRole("region", { name: "Eight dimension discovery" });
  const profile = panel.getByRole("combobox", { name: "Analogue comparison profile" });
  await profile.selectOption("geology_materials");
  const top = panel.locator("summary").filter({ hasText: /^#1 / }).first();
  await expect(top).toContainText(/Mojave/i, { timeout: 15000 });
  await top.click();
  const candidate = top.locator("..");
  const geology = candidate.locator("details").filter({ has: page.locator("summary").filter({ hasText: /Geology, minerals/ }) }).first();
  await geology.locator("summary").first().click();
  await expect(geology.getByText(/mafic volcanic.*mafic volcanic/)).toBeVisible();
  await expect(geology.getByText(/Map scales:/)).toBeVisible();
  await expect(geology.getByText(/Weighted score contribution .*before normalization/)).toBeVisible();
  await expect(geology.getByRole("link").first()).toBeVisible();
  const operations = candidate.locator("details").filter({ has: page.locator("summary").filter({ hasText: /Mission operations/ }) }).first();
  await operations.locator("summary").first().click();
  await expect(operations.getByText(/Uses terrain comparison measurements/)).toBeVisible();
  const thermal = candidate.locator("details").filter({ has: page.locator("summary").filter({ hasText: /Temperature (?:&|and) illumination/ }) }).first();
  await thermal.locator("summary").first().click();
  await expect(thermal.getByText(/Assigned weight .*effective weight 0\.000/)).toBeVisible();
});
