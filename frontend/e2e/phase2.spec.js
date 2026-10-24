import { expect, test } from "@playwright/test";

const ready = Boolean(process.env.CC_E2E_BACKEND);

test.describe("Phase 2 review against D+E", () => {
  test.skip(
    !ready,
    "Phase 2 backend e2e waits for slices D and E. Run with CC_E2E_BACKEND=1 and CC_POSE_BACKEND=fixture after they merge. Merge order is D, then E, then F.",
  );

  test("reviews a fixture video with the keyboard only", async ({ page }) => {
    const sample = process.env.CC_E2E_VIDEO;
    test.skip(!sample, "Set CC_E2E_VIDEO to a fixture file after D and E merge.");
    await page.goto("/library");
    await expect(page.getByRole("heading", { name: "Library" })).toBeVisible();
    await page.locator('input[type="file"]').setInputFiles(sample);
    await expect(page.getByText("100%")).toBeVisible({ timeout: 60_000 });
    await page.getByRole("link", { name: "Open" }).first().click();
    await expect(page.getByRole("button", { name: "Finish review" })).toBeVisible({ timeout: 60_000 });
    await page.keyboard.press("Enter");
    await page.keyboard.press("Enter");
    const finish = page.getByRole("button", { name: "Finish review" });
    await expect(finish).toBeEnabled({ timeout: 30_000 });
    await finish.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByText("This video is reviewed.")).toBeVisible({ timeout: 30_000 });
  });
});
