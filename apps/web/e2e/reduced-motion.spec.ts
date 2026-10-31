import { expect, test } from "playwright/test";
import { expectNoCriticalAxeViolations, installAuthenticatedSession } from "./helpers";

test("@reduced-motion removes decorative motion without hiding operational state", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await installAuthenticatedSession(page);
  await page.goto("/dashboard");
  await expect(page.getByText("All systems operational")).toBeVisible();
  expect(await page.evaluate(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches)).toBe(true);

  const motion = await page.evaluate(() => {
    const toMilliseconds = (value: string) => value.endsWith("ms") ? Number.parseFloat(value) : Number.parseFloat(value) * 1_000;
    let maximumDuration = 0;
    for (const element of Array.from(document.querySelectorAll("*"))) {
      const style = window.getComputedStyle(element);
      for (const value of [...style.animationDuration.split(","), ...style.transitionDuration.split(",")]) {
        maximumDuration = Math.max(maximumDuration, toMilliseconds(value.trim()));
      }
    }
    return { maximumDuration, scrollBehavior: window.getComputedStyle(document.documentElement).scrollBehavior };
  });

  expect(motion.maximumDuration).toBeLessThanOrEqual(0.011);
  expect(motion.scrollBehavior).toBe("auto");
  await expectNoCriticalAxeViolations(page);
});
