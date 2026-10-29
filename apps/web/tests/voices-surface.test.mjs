import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const webRoot = resolve(import.meta.dirname, '..');

test('voice workflow has list, create, and detail routes inside the protected shell', () => {
  for (const route of [
    'app/(protected)/voices/page.tsx',
    'app/(protected)/voices/new/page.tsx',
    'app/(protected)/voices/[voiceId]/page.tsx',
    'components/voices/VoiceListScreen.tsx',
    'components/voices/VoiceCreateScreen.tsx',
    'components/voices/VoiceDetailScreen.tsx',
  ]) {
    assert.equal(existsSync(resolve(webRoot, route)), true, route);
  }
});

test('voice create surface enforces consent and documented audio constraints', () => {
  const createSource = readFileSync(resolve(webRoot, 'components/voices/VoiceCreateScreen.tsx'), 'utf8');
  assert.match(createSource, /consent_unread/);
  assert.match(createSource, /I own this voice or have permission/);
  assert.match(createSource, /25_000_000/);
  assert.match(createSource, /WAV, MP3, or M4A/);
  assert.match(createSource, /6–30 seconds/);
  assert.match(createSource, /No audio file was sent or stored/);
});

test('voice screens cover filters and destructive lifecycle confirmations', () => {
  const listSource = readFileSync(resolve(webRoot, 'components/voices/VoiceListScreen.tsx'), 'utf8');
  const detailSource = readFileSync(resolve(webRoot, 'components/voices/VoiceDetailScreen.tsx'), 'utf8');
  assert.match(listSource, /Clear filters/);
  assert.match(listSource, /Loading voice profiles/);
  assert.match(listSource, /Voice profiles could not be loaded/);
  assert.match(detailSource, /Revoke consent/);
  assert.match(detailSource, /Delete permanently/);
  assert.match(detailSource, /Type the voice name to confirm/);
  assert.match(detailSource, /deletion is disabled until the voice loads successfully/);
  assert.match(detailSource, /role="dialog"/);
});
