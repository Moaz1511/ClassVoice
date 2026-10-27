import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';

test('web workspace has the placeholder health server used by the local stack', () => {
  const healthServer = resolve(import.meta.dirname, '../../../infra/docker/health_server.mjs');
  assert.equal(existsSync(healthServer), true);
});
