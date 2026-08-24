import { expect, test } from "@playwright/test";

test.describe("SimulationCard", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("API online")).toBeVisible({ timeout: 15_000 });
  });

  test("computes a minimum deterrence penalty for the default inputs", async ({ page }) => {
    await page.getByTestId("compute-penalty-button").click();

    const result = page.getByTestId("penalty-result");
    await expect(result).toBeVisible({ timeout: 10_000 });
    // benefit=1000, cost_compliance=50, p_detect=0.3 ->
    // ((1-0.3)*1000 + 50) / 0.3 = 2500.00 (game_theory/penalty_optimizer.py)
    await expect(page.getByTestId("row-value-deterrence-threshold")).toHaveText("2500.00");
    await expect(page.getByTestId("row-value-compliance-is-dominant")).toHaveText("yes");
  });

  test("plots the convex penalty curve", async ({ page }) => {
    await page.getByTestId("plot-curve-button").click();

    const chart = page.getByTestId("penalty-curve-chart");
    await expect(chart).toBeVisible({ timeout: 10_000 });
    const points = await chart.locator("polyline").getAttribute("points");
    expect(points).toBeTruthy();
    // 11 sample points are requested (SimulationCard.tsx) -> 11 "x,y" pairs.
    expect(points!.trim().split(" ")).toHaveLength(11);
  });
});
