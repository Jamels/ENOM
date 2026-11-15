import { test, expect } from "@playwright/test";

for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
  test(`Sparse MOLA evidence gate at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    page.on("response", async (response) => {
      if (response.url().includes("/api/discovery/")) {
        const payload = response.request().postData() ?? "";
        const body = await response.text().catch(() => "<response body unavailable>");
        console.log(JSON.stringify({ url: response.url(), status: response.status(), request: payload, response: body.slice(0, 1200) }));
      }
    });
    await page.goto("/");
    const started = Date.now();
    const rankResponse = page.waitForResponse((response) => response.url().endsWith("/api/discovery/rank") && response.status() === 200);
    await page.getByRole("button", { name: "Find terrain near mars_aeolis_nondune-01" }).click();
    await expect(page.getByText("Exploratory comparison · limited evidence")).toBeVisible();
    console.log(`Mars selection to result at ${viewport.width}px: ${Date.now() - started} ms`);
    const ranking = await (await rankResponse).json();
    expect(ranking.status).toBe("ranked");
    expect(ranking.results.length).toBeGreaterThan(0);
    expect(ranking.results[0].evidence_class).toBe("limited_evidence");
    expect(ranking.results[0].matched_variable_count).toBe(1);
    await expect(page.getByText(/Observed MOLA bins: 153\/484 · 31\.6%/)).toBeVisible();
    await expect(page.getByText(/excluded from ranking when support is incomplete/)).toHaveCount(0);
    await expect(page.getByText(/analysed mars_aeolis_nondune-01/)).toBeVisible();
  });
  test(`Moon discovery at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.goto("/");
    await page.getByRole("tab", { name: "Moon", exact: true }).click();
    await page.getByRole("button", { name: /Find terrain near LOLA south-polar terrain · Shackleton/ }).click();
    await expect(page.getByText("Multi-feature terrain comparison · experimental")).toBeVisible();
    await expect(page.getByText(/analysed lola_polar_moon_shackleton_rim/)).toBeVisible();
    await expect(page.getByText(/5\/5 features · multi feature/).first()).toBeVisible();
  });
}

test("late response from an old selection cannot replace a newer selection", async ({ page }) => {
  await page.goto("/");
  let releaseOld: (() => void) | undefined;
  const hold = new Promise<void>((resolve) => { releaseOld = resolve; });
  await page.route("**/api/discovery/resolve", async (route) => {
    const data = route.request().postDataJSON();
    if (data.latitude_deg < -2 && data.latitude_deg > -4) await hold;
    await route.continue().catch(() => {});
  });
  await page.getByRole("button", { name: "Find terrain near mars_aeolis_nondune-01" }).click();
  await page.getByRole("tab", { name: "Moon", exact: true }).click();
  await page.getByRole("button", { name: /Find terrain near LOLA south-polar terrain · Shackleton/ }).click();
  await expect(page.getByText("Multi-feature terrain comparison · experimental")).toBeVisible();
  releaseOld?.();
  await expect(page.getByText(/analysed lola_polar_moon_shackleton_rim/)).toBeVisible();
  await expect(page.getByText(/analysed mars_aeolis_nondune-01/)).toHaveCount(0);
});

test("surface clicks outside indexed coverage do not create a ranking", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  const canvas = page.locator("canvas").first();
  const bounds = await canvas.boundingBox();
  if (!bounds) throw new Error("Mars globe canvas unavailable");
  await canvas.click({ position: { x: bounds.width * 0.42, y: bounds.height * 0.4 } });
  await expect(page.getByRole("status").filter({ hasText: /No indexed terrain window covers this point/ })).toBeVisible();
});

test("planetary globe explains indexed and unindexed terrain colors", async ({ page }) => {
  await page.goto("/");
  let legend = page.getByRole("region", { name: "Terrain coverage legend" });
  await expect(legend).toBeVisible();
  await expect(legend.getByText(/Teal: indexed terrain window · click to inspect/)).toBeVisible();
  await expect(legend.getByText(/No teal: no indexed terrain here; click for nearest windows/)).toBeVisible();
  const indexedMarker = page.getByRole("button", { name: /Indexed terrain: mars_aeolis_nondune-01/ });
  await expect(indexedMarker.locator("span.relative > span")).toHaveCSS("background-color", "rgb(45, 212, 191)");

  await page.getByRole("tab", { name: "Moon", exact: true }).click();
  legend = page.getByRole("region", { name: "Terrain coverage legend" });
  await expect(legend.getByText(/alignment with the global basemap is unverified/)).toBeVisible();
});

test("selecting an indexed marker on the globe starts discovery", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  const marker = page.getByRole("button", { name: /Indexed terrain: mars_aeolis_nondune-01/ });
  // The marker starts on the far side of the globe. Keyboard focus rotates it
  // into view, after which a real pointer click can select it.
  await marker.focus();
  await marker.click();
  await expect(page.getByText(/analysed mars_aeolis_nondune-01/)).toBeVisible();
  await expect(page.getByText("Exploratory comparison · limited evidence")).toBeVisible();
});

test("ranking automatically focuses Earth on the top recommendation", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  const responsePromise = page.waitForResponse((response) =>
    response.url().endsWith("/api/discovery/rank") && response.status() === 200 &&
    response.request().postDataJSON()?.context_id === "mars_aeolis_nondune-01",
  );
  await page.getByRole("button", { name: "Find terrain near mars_aeolis_nondune-01" }).click();
  const ranking = await (await responsePromise).json();
  const top = ranking.recommendations[0].context.index_center;
  let observed: Record<string, unknown> = {};
  try {
    await expect.poll(async () => {
      const view = page.getByTestId("earth-view");
      const latitude = Number(await view.getAttribute("data-lat"));
      const longitude = Number(await view.getAttribute("data-lon"));
      const longitudeDifference = Math.abs(((longitude - top.longitude_east_deg + 540) % 360) - 180);
      observed = { latitude, longitude, target: top };
      return Math.abs(latitude - top.latitude_deg) < 1.5 && longitudeDifference < 1.5;
    }, { timeout: 10000 }).toBe(true);
  } catch (error) {
    console.log(`Earth camera focus diagnostics: ${JSON.stringify(observed)}`);
    throw error;
  }
});

test("optional land-cover limits filter the Earth candidates", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await page.getByRole("button", { name: "Find terrain near mars_aeolis_nondune-01" }).click();
  await expect(page.getByText("Exploratory comparison · limited evidence")).toBeVisible();
  await page.getByText("Land-cover limits (optional)").click();
  for (const label of ["Bare or sparse", "Forest", "Cropland", "Built up", "Snow and ice", "Water", "Grass, shrub, wetland"]) {
    await page.getByRole("spinbutton", { name: `${label} maximum percent` }).fill("0");
  }
  await expect(page.getByText("No eligible Earth contexts satisfy the selected land-cover limits and evidence requirements.")).toBeVisible();
  await expect(page.getByText(/contexts lack complete land-cover evidence; \d+ fail the selected limits/)).toBeVisible();
});

test("Moon indexed discovery keeps its scorecard action after Earth recommendations load", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("tab", { name: "Moon", exact: true }).click();
  await page.getByRole("button", { name: /Find terrain near LOLA south-polar terrain · Shackleton/ }).click();
  await expect(page.getByText("Multi-feature terrain comparison · experimental")).toBeVisible();
  const scorecard = page.getByRole("button", { name: "Scorecard", exact: true });
  await expect(scorecard).toBeVisible();
  await scorecard.click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Evidence dimensions" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Terrain comparison measurements" })).toBeVisible();
  await expect(page.getByText(/not a probability, geological validation, or mission-suitability result/)).toBeVisible();
});

test("out-of-coverage Moon click offers a direct route to the nearest indexed window", async ({ page }) => {
  let firstResolve = true;
  await page.route("**/api/discovery/resolve", async (route) => {
    const click = route.request().postDataJSON();
    if (firstResolve && click.body === "moon") {
      firstResolve = false;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ index_id: "fixture", click, status: "out_of_coverage", coordinate_frame: "lola_mean_earth", contexts: [] }),
      });
      return;
    }
    await route.continue();
  });
  await page.goto("/");
  await page.getByRole("tab", { name: "Moon", exact: true }).click();
  const globe = page.locator("canvas").first();
  const bounds = await globe.boundingBox();
  if (!bounds) throw new Error("Moon globe canvas unavailable");
  await globe.click({ position: { x: bounds.width * 0.5, y: bounds.height * 0.5 } });
  await expect(page.getByRole("heading", { name: "Nearest indexed terrain windows" })).toBeVisible();
  const nearest = page.getByRole("button", { name: /^Compare near .+ · \d+ km$/ }).first();
  await expect(nearest).toBeVisible();
  await nearest.click();
  await expect(page.getByText(/analysed lola_polar_moon_/)).toBeVisible();
});
