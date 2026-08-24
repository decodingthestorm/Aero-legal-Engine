import { expect, test } from "@playwright/test";

test.describe("Dashboard", () => {
  test("loads and reports the API as online", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("Legal Engine Platform")).toBeVisible();
    await expect(page.getByText("API online")).toBeVisible({ timeout: 15_000 });
  });

  test("navigates to the knowledge graph page", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: "Knowledge Graph" }).click();
    await expect(page).toHaveURL(/\/graph$/);
    await expect(page.getByRole("heading", { name: "Knowledge Graph" })).toBeVisible();
  });
});
