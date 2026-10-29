import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";

const root = resolve(import.meta.dirname, "..");
const read = (path) => readFileSync(resolve(root, path), "utf8");

test("settings and safety routes use dedicated screens", () => {
  for (const route of [
    "app/(protected)/settings/profile/page.tsx",
    "app/(protected)/settings/workspace/page.tsx",
    "app/(protected)/settings/safety/page.tsx",
    "app/(protected)/admin/audit/page.tsx",
    "app/(protected)/admin/reports/page.tsx",
  ]) {
    assert.equal(existsSync(resolve(root, route)), true, route);
  }
  assert.match(read("components/settings/ProfileSettingsScreen.tsx"), /ProfileSettingsScreen/);
  assert.match(read("components/settings/WorkspaceSettingsScreen.tsx"), /WorkspaceSettingsScreen/);
  assert.match(read("components/settings/SafetySettingsScreen.tsx"), /SafetySettingsScreen/);
});

test("profile deletion and export controls are guarded and truthful", () => {
  const source = read("components/settings/ProfileSettingsScreen.tsx");
  assert.match(source, /Request export/);
  assert.match(source, /Re-enter password/);
  assert.match(source, /DELETE MY ACCOUNT/);
  assert.match(source, /queues workspace and asset cascade cleanup/);
  assert.match(source, /Voice profiles, consent records, samples, projects, generation jobs, and outputs/);
  assert.match(source, /no account mutation was sent/);
});

test("audit screen exposes safe filters without private payloads", () => {
  const source = read("components/admin/AuditScreen.tsx");
  assert.match(source, /append-only/);
  assert.match(source, /source text/);
  assert.match(source, /signed URLs/);
  assert.match(source, /Search request or resource ID/);
  assert.match(source, /No audit events yet/);
});

test("reports screen bounds descriptions and avoids raw content", () => {
  const source = read("components/admin/ReportsScreen.tsx");
  assert.match(source, /consent_concern/);
  assert.match(source, /maxLength={2_000}/);
  assert.match(source, /no report was sent/);
  assert.match(source, /No reports to review/);
  assert.match(source, /Do not paste source text, audio, secrets, or private URLs/);
});
