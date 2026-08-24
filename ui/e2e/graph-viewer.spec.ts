import { expect, test } from "@playwright/test";

// The API's graph/vector state is in-process and shared across the whole
// test run (see playwright.config.ts) - every citation/entity id used here
// is unique per test run so tests can't interfere with each other or with
// re-runs against an already-populated dev server.
function unique(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

test.describe("GraphViewer", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/graph");
    await expect(page.getByText("API online")).toBeVisible({ timeout: 15_000 });
  });

  test("adds a statute and resolves it as governing its entity", async ({ page }) => {
    const citation = unique("Sec. E2E");
    const entityId = unique("entity-e2e");

    await page.getByLabel("Citation").fill(citation);
    await page.getByLabel("Applies to (entity ids, csv)").fill(entityId);
    await page.getByTestId("add-statute-button").click();
    await expect(page.getByTestId("add-statute-status")).toContainText(citation, { timeout: 10_000 });

    await page.getByTestId("preemption-entity-input").fill(entityId);
    await page.getByTestId("preemption-resolve-button").click();

    const result = page.getByTestId("preemption-result");
    await expect(result).toBeVisible({ timeout: 10_000 });
    await expect(result).toContainText("Governing:");
    await expect(result).toContainText(citation);
  });

  test("shows a friendly message for an entity with no statutes", async ({ page }) => {
    await page.getByTestId("preemption-entity-input").fill(unique("entity-empty"));
    await page.getByTestId("preemption-resolve-button").click();
    await expect(page.getByTestId("preemption-result")).toContainText(
      "No statutes are tied to this entity.",
      { timeout: 10_000 }
    );
  });

  test("state statute preempts a conflicting municipal statute", async ({ page }) => {
    const entityId = unique("entity-preemption");
    const stateCitation = unique("State STR Permit");
    const muniCitation = unique("Muni STR Ban");

    await page.getByLabel("Source type").selectOption("state_statute");
    await page.getByLabel("Jurisdiction tier").selectOption({ label: "State" });
    await page.getByLabel("Citation").fill(stateCitation);
    await page.getByLabel("Applies to (entity ids, csv)").fill(entityId);
    await page.getByTestId("add-statute-button").click();
    await expect(page.getByTestId("add-statute-status")).toContainText(stateCitation, { timeout: 10_000 });

    await page.getByLabel("Source type").selectOption("municipal_code");
    await page.getByLabel("Jurisdiction tier").selectOption({ label: "Municipal" });
    await page.getByLabel("Citation").fill(muniCitation);
    await page.getByLabel("Applies to (entity ids, csv)").fill(entityId);
    await page.getByTestId("add-statute-button").click();
    await expect(page.getByTestId("add-statute-status")).toContainText(muniCitation, { timeout: 10_000 });

    await page.getByTestId("preemption-entity-input").fill(entityId);
    await page.getByTestId("preemption-resolve-button").click();

    const result = page.getByTestId("preemption-result");
    await expect(result).toContainText(stateCitation, { timeout: 10_000 });
    await expect(result).toContainText("Preempts:");
    await expect(result).toContainText(muniCitation);
  });

  test("finds a newly-added statute via semantic search", async ({ page }) => {
    // A random token embedded in both the statute text and the search
    // query, rather than relying on the panel's generic default query
    // ("short-term rental permit") matching against generic default statute
    // text: other tests in this suite add statutes with that same generic
    // wording, and if this suite runs repeatedly against an already-running
    // dev server (reuseExistingServer — see playwright.config.ts) without
    // restarting it, those accumulate across runs and could eventually
    // crowd this test's target out of the top-5 results. An unlikely-to-
    // collide token keeps the match unambiguous regardless of what else has
    // piled up in the shared in-memory index.
    const token = unique("distinctivephrase").replace(/[^a-z0-9]/gi, "");
    const citation = unique("Sec. E2E-Search");

    await page.getByLabel("Citation").fill(citation);
    await page.getByLabel("Text").fill(`Statute concerning ${token} zoning requirements.`);
    await page.getByLabel("Applies to (entity ids, csv)").fill(unique("entity-search"));
    await page.getByTestId("add-statute-button").click();
    await expect(page.getByTestId("add-statute-status")).toContainText(citation, { timeout: 10_000 });

    await page.getByTestId("search-query-input").fill(token);
    await page.getByTestId("search-button").click();
    await expect(page.getByTestId("search-results")).toContainText(citation, { timeout: 10_000 });
  });
});
