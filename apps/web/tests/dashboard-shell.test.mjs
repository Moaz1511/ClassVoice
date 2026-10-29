import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const webRoot = resolve(import.meta.dirname, '..');

test('protected dashboard has an authenticated shell and catch-all placeholders', () => {
  assert.equal(existsSync(resolve(webRoot, 'app/(protected)/layout.tsx')), true);
  assert.equal(existsSync(resolve(webRoot, 'app/(protected)/dashboard/page.tsx')), true);
  assert.equal(existsSync(resolve(webRoot, 'app/(protected)/[...slug]/page.tsx')), true);

  const protectedLayout = readFileSync(resolve(webRoot, 'app/(protected)/layout.tsx'), 'utf8');
  assert.match(protectedLayout, /ProtectedRoute/);
  assert.match(protectedLayout, /AppShell/);
});

test('dashboard shell exposes workspace switching and intentional state patterns', () => {
  const appShell = readFileSync(resolve(webRoot, 'components/layout/AppShell.tsx'), 'utf8');
  const pageState = readFileSync(resolve(webRoot, 'components/ui/PageState.tsx'), 'utf8');
  const placeholder = readFileSync(resolve(webRoot, 'components/ui/PlaceholderPage.tsx'), 'utf8');

  assert.match(appShell, /WorkspaceSwitcher/);
  assert.match(appShell, /Mobile workspace navigation/);
  assert.match(pageState, /LoadingState/);
  assert.match(pageState, /EmptyState/);
  assert.match(pageState, /ErrorState/);
  assert.match(placeholder, /No private data is loaded/);
});
