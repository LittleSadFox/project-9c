import { expect, test } from "@playwright/test";

const ready = Boolean(process.env.CC_E2E_BACKEND);
const sample = process.env.CC_E2E_VIDEO;

test.describe("Phase 1 flow", () => {
  test.skip(
    !ready,
    "Phase 1 e2e waits for slices A and B. Run with CC_E2E_BACKEND=1 and CC_POSE_BACKEND=fixture after they merge. This spec must not block the slice C local run.",
  );

  test("import, play overlay, cut, and keep a rating", async ({ page }) => {
    test.skip(!sample, "Set CC_E2E_VIDEO to a sample file after A and B merge.");
    await page.goto("/library");
    await expect(page.getByRole("heading", { name: "Library" })).toBeVisible();
    await page.locator('input[type="file"]').setInputFiles(sample);
    await expect(page.getByText("100%")).toBeVisible({ timeout: 60_000 });
    await page.getByRole("link", { name: "Open" }).first().click();
    await expect(page.getByRole("button", { name: "Create attempt" })).toBeVisible({ timeout: 60_000 });
    await page.keyboard.press("i");
    await page.keyboard.press("Shift+ArrowRight");
    await page.keyboard.press("o");
    await page.getByRole("button", { name: "Create attempt" }).click();
    await expect(page.getByText("Rating")).toBeVisible({ timeout: 30_000 });
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByText("Saved")).toBeVisible({ timeout: 10_000 });
    await page.reload();
    await expect(page.getByRole("button", { name: "Send" })).toBeVisible();
  });
});
