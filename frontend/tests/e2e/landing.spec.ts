import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.describe("Landing page", () => {
  test("renders the header and hero section", async ({ page }) => {
    await page.goto("/");

    await expect(
      page.locator("header").first().getByText("vectoree-deer-flow", { exact: true }),
    ).toBeVisible();
    await expect(page.locator("h1")).toHaveCount(1);
    await expect(page.locator("h1")).toContainText("vectoree-deer-flow");

    // "Get Started" call-to-action button in hero
    await expect(
      page.getByRole("button", { name: /get started/i }),
    ).toBeVisible();
  });

  for (const width of [320, 375, 390]) {
    test(`does not overflow at ${width}px width`, async ({ page }) => {
      await page.setViewportSize({ width, height: 812 });
      await page.goto("/");

      await expect
        .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
        .toBeLessThanOrEqual(width);
      await expect(page.locator("main").first()).toBeInViewport();
    });
  }

  test("Get Started opens login when linked but signed out", async ({ page }) => {
    mockLangGraphAPI(page);
    await page.route("**/api/vectoree/link-status", (route) =>
      route.fulfill({ json: { linked: true } }),
    );
    await page.route("**/api/v1/auth/me", (route) =>
      route.fulfill({ status: 401, json: { detail: "unauthorized" } }),
    );
    await page.route("**/api/v1/auth/setup-status", (route) =>
      route.fulfill({ json: { needs_setup: false, vectoree_linked: false } }),
    );

    await page.goto("/");

    const getStarted = page.getByRole("button", { name: /get started/i });
    await getStarted.click();

    await page.waitForURL("**/login**");
    await expect(page).toHaveURL(/\/login/);
  });

  test("Get Started opens login when the backend is already linked", async ({
    page,
  }) => {
    await page.route("**/api/vectoree/link-status", (route) =>
      route.fulfill({ json: { linked: false } }),
    );
    await page.route("**/api/v1/auth/setup-status", (route) =>
      route.fulfill({ json: { needs_setup: false, vectoree_linked: true } }),
    );
    await page.route("**/api/v1/auth/me", (route) =>
      route.fulfill({ status: 401, json: { detail: "unauthorized" } }),
    );

    await page.goto("/");
    await page.getByRole("button", { name: /get started/i }).click();
    await page.waitForURL("**/login**");
    await expect(page).toHaveURL(/\/login/);
  });

  test("Get Started skips the link page in cloud mode", async ({ page }) => {
    await page.route("**/api/vectoree/link-status", (route) =>
      route.fulfill({ json: { linked: false, deployMode: "cloud" } }),
    );
    await page.route("**/api/v1/auth/setup-status", (route) =>
      route.fulfill({ json: { needs_setup: false, vectoree_linked: false } }),
    );
    await page.route("**/api/v1/auth/me", (route) =>
      route.fulfill({ status: 401, json: { detail: "unauthorized" } }),
    );

    await page.goto("/");
    await page.getByRole("button", { name: /get started/i }).click();
    await page.waitForURL("**/login**");
    await expect(page).toHaveURL(/\/login/);
  });

  test("Get Started opens the Vectoree link page when unlinked", async ({
    page,
  }) => {
    await page.route("**/api/vectoree/link-status", (route) =>
      route.fulfill({ json: { linked: false } }),
    );
    await page.route("**/api/v1/auth/setup-status", (route) =>
      route.fulfill({ json: { needs_setup: false, vectoree_linked: false } }),
    );

    await page.goto("/");
    await page.getByRole("button", { name: /get started/i }).click();
    await page.waitForURL("**/link");
    await expect(
      page.getByRole("heading", { name: "Link Vectoree" }),
    ).toBeVisible();
  });
});
