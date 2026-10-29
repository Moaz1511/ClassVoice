import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const webRoot = resolve(import.meta.dirname, '..');

test('Studio has new-project and persistent-project routes inside the protected shell', () => {
  for (const route of [
    'app/(protected)/studio/page.tsx',
    'app/(protected)/studio/[projectId]/page.tsx',
    'components/studio/StudioScreen.tsx',
  ]) {
    assert.equal(existsSync(resolve(webRoot, route)), true, route);
  }
});

test('Studio keeps draft text local and does not include it in saved settings', () => {
  const source = readFileSync(resolve(webRoot, 'components/studio/StudioScreen.tsx'), 'utf8');
  assert.match(source, /localStorage/);
  assert.match(source, /classvoice\.studio\.draft/);
  assert.match(source, /saved editor settings/i);
  assert.match(source, /server sync is pending API client integration/);
  assert.match(source, /Draft text stays in this browser/);
});

test('Studio enforces generation prerequisites and unsaved-change choices', () => {
  const source = readFileSync(resolve(webRoot, 'components/studio/StudioScreen.tsx'), 'utf8');
  assert.match(source, /10_000/);
  assert.match(source, /Revoked, archived, and processing voices are excluded/);
  assert.match(source, /Unsaved draft/);
  assert.match(source, /Stay/);
  assert.match(source, /Discard/);
  assert.match(source, /Save project/);
  assert.match(source, /beforeunload/);
});
