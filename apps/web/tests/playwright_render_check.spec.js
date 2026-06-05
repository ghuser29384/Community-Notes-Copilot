const { test, expect } = require("@playwright/test");

test("operator UI renders candidate workflow and mobile admission", async ({ page }) => {
  await page.goto("http://127.0.0.1:8000", { waitUntil: "networkidle" });
  await expect(page.locator("h1")).toHaveText("Dashboard");
  await page.click("#sync-button");
  await page.waitForTimeout(300);

  await page.goto("http://127.0.0.1:8000/candidates", { waitUntil: "networkidle" });
  await expect(page.locator("table")).toBeVisible();
  await page.locator("a[href^='/candidates/']").first().click();
  await expect(page.locator("text=Post context")).toBeVisible();

  await page.click("button[data-action=analyze]");
  await page.waitForTimeout(200);
  await page.click("button[data-action=retrieve]");
  await page.waitForTimeout(200);
  await page.click("button[data-action=drafts]");
  await page.waitForTimeout(300);
  await expect(page.locator("text=DRAFTED").first()).toBeVisible();
  await page.screenshot({ path: "/private/tmp/cn-candidate-detail.png", fullPage: true });

  await page.setViewportSize({ width: 390, height: 900 });
  await page.goto("http://127.0.0.1:8000/admission", { waitUntil: "networkidle" });
  await expect(page.locator("text=Readiness")).toBeVisible();
  await page.screenshot({ path: "/private/tmp/cn-admission-mobile.png", fullPage: true });
});
