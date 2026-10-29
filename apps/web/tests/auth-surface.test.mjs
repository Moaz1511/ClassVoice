import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const webRoot = resolve(import.meta.dirname, '..');

test('auth route surface covers the documented P3-02 states', () => {
  for (const route of [
    'app/auth/sign-up/page.tsx',
    'app/auth/sign-in/page.tsx',
    'app/auth/verify-email/page.tsx',
    'app/auth/reset-password/page.tsx',
    'app/auth/callback/page.tsx',
    'app/onboarding/page.tsx',
  ]) {
    assert.equal(existsSync(resolve(webRoot, route)), true, route);
  }
});

test('browser auth adapter does not persist an access token', () => {
  const authSource = readFileSync(resolve(webRoot, 'lib/auth.ts'), 'utf8');
  assert.match(authSource, /sessionStorage/);
  assert.doesNotMatch(authSource, /localStorage/);
  assert.match(authSource, /accessToken: string/);
});
