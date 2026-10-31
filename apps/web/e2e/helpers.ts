import axe from "axe-core";
import { expect, type Locator, type Page } from "playwright/test";

type AxeViolation = Readonly<{
  id: string;
  impact: string | null;
  help: string;
  nodes: ReadonlyArray<Readonly<{ target: unknown; failureSummary?: string }>>;
}>;

export async function installAuthenticatedSession(page: Page): Promise<void> {
  await page.addInitScript(() => {
    window.sessionStorage.setItem("classvoice.session.active", String(Date.now() + 60 * 60 * 1_000));
  });
}

export async function expectNoCriticalAxeViolations(page: Page): Promise<void> {
  await page.addScriptTag({ content: axe.source });
  const violations = await page.evaluate(async () => {
    const axeApi = (window as unknown as {
      axe: {
        run: (context: Document, options: object) => Promise<{ violations: AxeViolation[] }>;
      };
    }).axe;
    const result = await axeApi.run(document, {
      runOnly: {
        type: "tag",
        values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"],
      },
      resultTypes: ["violations"],
    });
    return result.violations;
  });
  const critical = violations.filter((violation) => violation.impact === "critical");
  const details = critical.map((violation) => `${violation.id}: ${violation.help}\n${violation.nodes.map((node) => `  ${JSON.stringify(node.target)} ${node.failureSummary ?? ""}`).join("\n")}`).join("\n");
  expect(critical, details || "No critical axe violations").toEqual([]);
}

export async function expectNoHorizontalPageOverflow(page: Page): Promise<void> {
  const dimensions = await page.evaluate(() => ({
    viewportWidth: window.innerWidth,
    documentWidth: document.documentElement.scrollWidth,
  }));
  expect(dimensions.documentWidth).toBeLessThanOrEqual(dimensions.viewportWidth + 1);
}

export async function tabTo(page: Page, target: Locator, maximumTabs = 100): Promise<void> {
  for (let index = 0; index < maximumTabs; index += 1) {
    await page.keyboard.press("Tab");
    if (await target.evaluate((element) => document.activeElement === element).catch(() => false)) return;
  }
  throw new Error(`Keyboard focus did not reach ${await target.getAttribute("aria-label") ?? await target.textContent() ?? "the target"}`);
}
