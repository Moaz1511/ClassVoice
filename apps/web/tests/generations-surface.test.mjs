import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const webRoot = resolve(import.meta.dirname, '..');

test('generation workflow has list and detail routes inside the protected shell', () => {
  for (const route of [
    'app/(protected)/generations/page.tsx',
    'app/(protected)/generations/[generationId]/page.tsx',
    'components/generations/GenerationListScreen.tsx',
    'components/generations/GenerationDetailScreen.tsx',
    'components/generations/GenerationStatusBadge.tsx',
  ]) {
    assert.equal(existsSync(resolve(webRoot, route)), true, route);
  }
});

test('generation list defines filters, truthful states, and bounded polling backoff', () => {
  const source = readFileSync(resolve(webRoot, 'components/generations/GenerationListScreen.tsx'), 'utf8');
  assert.match(source, /All states/);
  assert.match(source, /LoadingState/);
  assert.match(source, /ErrorState/);
  assert.match(source, /No generations yet/);
  assert.match(source, /Math\.min\(current \* 2, 8_000\)/);
  assert.match(source, /never duplicates a mutation/);
});

test('generation detail keeps output private and covers cancel, retry, playback, and safe download states', () => {
  const source = readFileSync(resolve(webRoot, 'components/generations/GenerationDetailScreen.tsx'), 'utf8');
  assert.match(source, /cancel_requested/);
  assert.match(source, /succeeded/);
  assert.match(source, /Cancel generation/);
  assert.match(source, /Retry generation/);
  assert.match(source, /Download signed output/);
  assert.match(source, /signed download URL/);
  assert.match(source, /private URL is exposed here/);
  assert.match(source, /Input text.*SHA-256 only/);
});
