import { expect, test } from "@playwright/test";

test("opens the shell", async ({ page }) => {
  await page.route("**/health", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        status: "ok",
        version: "0",
        db: "ok",
        ffmpeg: { version: "7", h264_encoder: "stub" },
        onnx: { providers: ["CPUExecutionProvider"], device: "cpu" },
        library_free_gb: 1,
        dev: false,
      }),
    });
  });
  await page.route("**/api/jobs**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ items: [], total: 0 }),
    });
  });
  await page.goto("/");
  await expect(page.getByText("Climbing Coach")).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Library" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Compare" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Progress" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Models" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Settings" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Library" })).toBeVisible();
});
