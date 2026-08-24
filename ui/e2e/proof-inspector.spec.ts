import { expect, test } from "@playwright/test";

test.describe("ProofInspector", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("API online")).toBeVisible({ timeout: 15_000 });
  });

  test("verifies a satisfiable clause and shows the SMT-LIB2 rendering", async ({ page }) => {
    await page.getByRole("button", { name: "Satisfiable: ownership implies reporting" }).click();
    await page.getByTestId("verify-button").click();

    const result = page.getByTestId("verify-result");
    await expect(result).toBeVisible({ timeout: 10_000 });
    await expect(result.getByText("SATISFIABLE", { exact: true })).toBeVisible();
    await expect(result.getByText(/declare-datatypes/)).toBeVisible();
  });

  test("verifies an unsatisfiable clause", async ({ page }) => {
    await page.getByRole("button", { name: "Unsatisfiable: alice owns but never reports" }).click();
    await page.getByTestId("verify-button").click();

    const result = page.getByTestId("verify-result");
    await expect(result).toBeVisible({ timeout: 10_000 });
    await expect(result.getByText("UNSATISFIABLE", { exact: true })).toBeVisible();
  });

  test("shows a client-side error for malformed matrix JSON", async ({ page }) => {
    await page.getByTestId("matrix-textarea").fill("{not valid json");
    await page.getByTestId("verify-button").click();
    await expect(page.getByTestId("verify-error")).toContainText(/not valid JSON/i);
    // Never reaches the API for a client-side JSON parse failure.
    await expect(page.getByTestId("verify-result")).toHaveCount(0);
  });

  test("shows the server's rejection reason for an unbound variable", async ({ page }) => {
    // forall_vars is "x" (loaded by default), but this atom references "y" -
    // formal_logic/epr_compiler.py rejects this as NotEPRFragmentError, and
    // api/middleware.py maps that to a 400 with a human-readable detail.
    await page
      .getByTestId("matrix-textarea")
      .fill(JSON.stringify({ kind: "atom", predicate: "Owns", args: [{ kind: "variable", name: "y" }] }));
    await page.getByTestId("verify-button").click();
    await expect(page.getByTestId("verify-error")).toContainText(/unbound variable/i, { timeout: 10_000 });
  });
});
