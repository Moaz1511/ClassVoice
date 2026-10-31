import { defineConfig } from "playwright/test";

const baseURL = "http://127.0.0.1:3100";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["line"], ["html", { open: "never" }]] : "line",
  use: {
    baseURL,
    browserName: "chromium",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  webServer: {
    command: "node .next/standalone/apps/web/server.js",
    url: baseURL,
    reuseExistingServer: false,
    timeout: 180_000,
    env: {
      ...process.env,
      CLASSVOICE_E2E_FIXTURES: "1",
      HOSTNAME: "127.0.0.1",
      NEXT_TELEMETRY_DISABLED: "1",
      PORT: "3100",
    },
  },
  projects: [
    { name: "responsive-375", grep: /@responsive/, use: { viewport: { width: 375, height: 812 } } },
    { name: "responsive-768", grep: /@responsive/, use: { viewport: { width: 768, height: 1024 } } },
    { name: "responsive-1024", grep: /@responsive/, use: { viewport: { width: 1024, height: 900 } } },
    { name: "responsive-1440", grep: /@responsive/, use: { viewport: { width: 1440, height: 1000 } } },
    { name: "keyboard-accessibility", grep: /@keyboard/, use: { viewport: { width: 1280, height: 900 } } },
    { name: "reduced-motion", grep: /@reduced-motion/, use: { viewport: { width: 1024, height: 900 }, reducedMotion: "reduce" } },
  ],
});
