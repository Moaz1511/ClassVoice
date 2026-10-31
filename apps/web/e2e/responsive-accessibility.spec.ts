import { expect, test } from "playwright/test";
import { expectNoCriticalAxeViolations, expectNoHorizontalPageOverflow, installAuthenticatedSession } from "./helpers";

const routes = [
  { path: "/dashboard", heading: "Good morning, Moaz" },
  { path: "/voices/new", heading: "Create a voice profile" },
  { path: "/studio", heading: "New lesson" },
  { path: "/generations/synthetic-succeeded", heading: "Output details" },
  { path: "/settings/profile", heading: "Profile settings" },
] as const;

test("@responsive protected workflows fit the viewport and have no critical axe violations", async ({ page }) => {
  await installAuthenticatedSession(page);

  for (const route of routes) {
    await page.goto(route.path);
    await expect(page.getByRole("heading", { level: 1, name: route.heading })).toBeVisible();
    await expectNoHorizontalPageOverflow(page);
    await expectNoCriticalAxeViolations(page);
  }

  await page.goto("/dashboard");
  const viewport = page.viewportSize();
  if (viewport && viewport.width <= 640) {
    await expect(page.locator(".sidebar")).toBeHidden();
    await expect(page.getByRole("navigation", { name: "Mobile workspace navigation" })).toBeVisible();
  } else {
    await expect(page.locator(".sidebar")).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Mobile workspace navigation" })).toBeHidden();
  }
});
