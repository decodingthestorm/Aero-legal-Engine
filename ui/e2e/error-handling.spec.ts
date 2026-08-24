import { expect, test } from "@playwright/test";

// README.md's "Known limitations" specifically flagged this as missing:
// "no error-path coverage (what does the UI show if the API is down
// mid-request, or a request 400s?)". Route interception simulates real
// failures without needing to actually kill the running API server mid-test.

test.describe("Error handling", () => {
  test("shows the API as unreachable when the health check fails", async ({ page }) => {
    await page.route("**/health", (route) => route.abort("connectionrefused"));
    await page.goto("/");
    await expect(page.getByText("API unreachable")).toBeVisible({ timeout: 15_000 });
  });

  test("SimulationCard surfaces a network failure as a visible error", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("API online")).toBeVisible({ timeout: 15_000 });

    await page.route("**/simulation/penalty", (route) => route.abort("connectionrefused"));
    await page.getByTestId("compute-penalty-button").click();

    // lib/api.ts's apiFetch throws ApiError for non-ok HTTP responses, but a
    // fully aborted request throws a plain fetch TypeError instead - the
    // component's catch falls back to String(err) for that case, so the
    // exact message is browser-dependent ("Failed to fetch" in Chromium).
    // What matters is that the UI shows *something* rather than silently
    // doing nothing when the request never completes.
    await expect(page.getByTestId("penalty-error")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId("penalty-result")).toHaveCount(0);
  });

  test("ProofInspector surfaces a 500 from the API as a visible error", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("API online")).toBeVisible({ timeout: 15_000 });

    await page.route("**/verification/verify", (route) =>
      route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ detail: "simulated internal error" }),
      })
    );
    await page.getByRole("button", { name: "Satisfiable: ownership implies reporting" }).click();
    await page.getByTestId("verify-button").click();

    await expect(page.getByTestId("verify-error")).toContainText("simulated internal error", {
      timeout: 10_000,
    });
    await expect(page.getByTestId("verify-result")).toHaveCount(0);
  });

  test("GraphViewer surfaces a 400 rejection as a visible error, not a silent failure", async ({
    page,
  }) => {
    await page.goto("/graph");
    await expect(page.getByText("API online")).toBeVisible({ timeout: 15_000 });

    await page.route("**/graph/statutes", (route) => {
      if (route.request().method() !== "POST") return route.continue();
      return route.fulfill({
        status: 400,
        contentType: "application/json",
        body: JSON.stringify({
          error: "NotEPRFragmentError",
          detail: "simulated validation failure",
          correlation_id: "test-correlation-id",
        }),
      });
    });
    await page.getByTestId("add-statute-button").click();

    await expect(page.getByTestId("add-statute-error")).toContainText("simulated validation failure", {
      timeout: 10_000,
    });
    await expect(page.getByTestId("add-statute-status")).toHaveCount(0);
  });
});
