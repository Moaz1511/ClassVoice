import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";

const webRoot = resolve(import.meta.dirname, "..");
const read = (path) => readFileSync(resolve(webRoot, path), "utf8");

test("API docs route is a dedicated protected screen", () => {
  assert.equal(existsSync(resolve(webRoot, "app/(protected)/docs/api/page.tsx")), true);
  assert.equal(existsSync(resolve(webRoot, "components/docs/ApiDocsScreen.tsx")), true);
  const page = read("app/(protected)/docs/api/page.tsx");
  assert.match(page, /ApiDocsScreen/);
});

test("API docs are generated from OpenAPI and expose the agent lifecycle", () => {
  const source = read("components/docs/ApiDocsScreen.tsx");
  assert.match(source, /packages\/api-client\/openapi\.json/);
  assert.match(source, /Create, poll, and download/);
  assert.match(source, /Idempotency-Key/);
  assert.match(source, /generations:create/);
  assert.match(source, /generations:read/);
  assert.match(source, /\/v1\/generations\/\$JOB_ID\/download/);
  assert.match(source, /10-minute private download URL/);
  assert.match(source, /Never place a Supabase service-role key/);
});

test("API docs include generated endpoint metadata and typed examples", () => {
  const source = read("components/docs/ApiDocsScreen.tsx");
  assert.match(source, /Object\.entries\(document\.paths\)/);
  assert.match(source, /Endpoint reference/);
  assert.match(source, /JavaScript agent request/);
  assert.match(source, /checkpoint_sha256/);
  assert.match(source, /storage keys, and secrets/);
});
