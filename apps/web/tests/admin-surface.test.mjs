import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const webRoot = resolve(import.meta.dirname, '..');

test('admin surfaces have protected API-key and webhook routes', () => {
  for (const route of [
    'app/(protected)/api-keys/page.tsx',
    'app/(protected)/webhooks/page.tsx',
    'components/admin/ApiKeysScreen.tsx',
    'components/admin/WebhooksScreen.tsx',
    'components/admin/SecretReveal.tsx',
  ]) {
    assert.equal(existsSync(resolve(webRoot, route)), true, route);
  }
});

test('API-key screen enforces scoped one-time secret and revoke behavior', () => {
  const source = readFileSync(resolve(webRoot, 'components/admin/ApiKeysScreen.tsx'), 'utf8');
  const secretSource = readFileSync(resolve(webRoot, 'components/admin/SecretReveal.tsx'), 'utf8');
  assert.match(source, /generations:create/);
  assert.match(source, /365 days/);
  assert.match(source, /No secret is generated in the browser/);
  assert.match(source, /Revoke this API key/);
  assert.match(secretSource, /Copy this secret before closing/);
  assert.match(secretSource, /cannot be shown again/);
  assert.match(secretSource, /navigator\.clipboard/);
});

test('webhook screen enforces HTTPS/SSRF-aware setup and delivery states', () => {
  const source = readFileSync(resolve(webRoot, 'components/admin/WebhooksScreen.tsx'), 'utf8');
  assert.match(source, /https:\/\//);
  assert.match(source, /private or loopback addresses/);
  assert.match(source, /generation\.succeeded/);
  assert.match(source, /pending_verification/);
  assert.match(source, /retrying/);
  assert.match(source, /No endpoint or secret was created in the browser/);
  assert.match(source, /Send test/);
});
