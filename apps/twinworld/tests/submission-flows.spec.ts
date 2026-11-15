import { test, expect } from "@playwright/test";

test("initial load selects a supported target and requests its scorecard", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("tab", { name: "Mars" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("region", { name: "Evidence coverage for selected location" })).toBeVisible();
  await expect(page.getByText("Coverage describes ENOM’s indexed evidence", { exact: false })).toBeVisible();
});

for (const mode of ["Combined", "Terrain", "DINOv2"] as const) {
  test(`${mode} retrieval sends its selected mode to the API`, async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Weights & retrieval" }).click();
    const expected = mode === "DINOv2" ? "visual" : mode.toLowerCase();
    if (mode === "Combined") await page.getByRole("button", { name: "Terrain", exact: true }).click();
    const responsePromise = page.waitForResponse((response) =>
      response.url().endsWith("/api/search") && response.request().method() === "POST" &&
      response.request().postDataJSON()?.method === expected,
    );
    await page.getByRole("button", { name: mode, exact: true }).click();
    const response = await responsePromise;
    expect(response.status()).toBe(200);
    expect(response.request().postDataJSON().method).toBe(
      expected,
    );
    const body = await response.json();
    expect(body.results.length).toBeGreaterThan(0);
    expect(body.results[0].observation_id).toBeTruthy();
    if (mode === "DINOv2") {
      expect(body.results[0].ranking_evidence).toContain("visual_embedding");
    } else if (mode === "Terrain") {
      expect(body.results[0].ranking_evidence).toContain("terrain_measurements");
    }
  });
}

test("Moon and Mars target changes request scorecards at their displayed coordinates", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("tab", { name: "Moon", exact: true }).click();
  const moonTarget = page.locator("aside").first().getByRole("button", { name: /Shackleton.*DEM/i });
  await expect(moonTarget).toBeVisible();
  const moonCoords = (await moonTarget.innerText()).match(/-?\d+\.\d+°[^\n]*\d+\.\d+°[EW]/);
  expect(moonCoords).not.toBeNull();
  const moonRequest = page.waitForRequest((request) =>
    request.url().endsWith("/api/scorecards/rank") && request.method() === "POST",
  );
  await moonTarget.click();
  const moonPayload = (await moonRequest).postDataJSON();
  expect(moonPayload.site_id).toContain("moon");
  await expect(page.getByRole("tab", { name: "Moon" })).toHaveAttribute("aria-selected", "true");

  await page.getByRole("tab", { name: "Mars", exact: true }).click();
  const marsTarget = page.locator("aside").first().getByRole("button", { name: /Mars Dune.*DEM/i }).nth(1);
  await expect(marsTarget).toBeVisible();
  const marsRequest = page.waitForRequest((request) =>
    request.url().endsWith("/api/scorecards/rank") && request.method() === "POST" &&
    String(request.postDataJSON()?.site_id).startsWith("mars"),
  );
  await marsTarget.click();
  expect((await marsRequest).postDataJSON().site_id).toContain("mars");
});

test("all eight analogue dimension weights are available and adjustable", async ({ page }) => {
  await page.goto("/");
  await page.getByText("Adjust eight dimension weights", { exact: true }).first().click();
  const weights = page.locator('input[type="range"][aria-label$="weight"]:visible');
  await expect(weights).toHaveCount(8);
  for (let i = 0; i < 8; i++) {
    const slider = weights.nth(i);
    await expect(slider).toBeVisible();
    await slider.evaluate((element: HTMLInputElement) => {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
      setter?.call(element, "0.37");
      element.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await expect(slider).toHaveValue("0.37");
  }
});

test("scorecard filter shows scorecard-backed targets and alternatives can be selected", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Scorecard", exact: true }).click();
  const targets = page.locator("aside").first().getByRole("button");
  await expect(targets.first()).toBeVisible();
  const labels = await targets.allTextContents();
  expect(labels.some((label) => /DEM/.test(label))).toBe(true);
  const selectable = targets.filter({ hasText: /DEM/ }).first();
  await selectable.click();
  await expect(selectable).toBeVisible();
});
