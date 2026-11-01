# P4-07 dependency, license, and secret review

Review date: 2026-11-01

Reviewed inputs: `package-lock.json`, `apps/api/requirements.txt`, Git tracked files/history, and `infra/model-registry/manifest.json`

## Automated results

| Gate | Command | Result |
|---|---|---|
| Production JavaScript vulnerabilities | `npm audit --omit=dev --audit-level=high` | Pass: 0 vulnerabilities in the production closure after upgrading Zod to 4.6.7 |
| Python runtime vulnerabilities | `python -m pip_audit -r apps/api/requirements.txt --progress-spinner off` | Pass: no known vulnerabilities |
| Repository and history secrets | `python scripts/scan_secrets.py --history` | Pass: no likely credentials in tracked files or added Git-history lines |
| Dependency/model licenses | `python scripts/check_licenses.py` in the API runtime image | Pass: no unknown, prohibited, or unapproved model license |

The initial production npm audit found GHSA-mrhx-c7xc-m3w5 in Zod versions below 4.6.6. The application pin and lockfile were updated from 4.1.12 to 4.6.7, then the production audit was repeated successfully.

## Manual license disposition

- OpenVoice V2 and its registered checkpoint are approved under MIT in ADR-001. The model remains disabled until runtime and performance release gates pass.
- The optional Sharp/libvips platform packages are LGPL-3.0-or-later. Distribution must preserve license notices and the user's ability to replace/relink the dynamically used library; published container/image notices must identify the corresponding source location.
- `caniuse-lite` data is CC-BY-4.0. Its attribution is preserved in `THIRD_PARTY_NOTICES.md` and release artifacts that redistribute the database must retain that attribution.
- No AGPL, SSPL, BUSL, Commons Clause, Elastic License, unknown license, or model with an unapproved review state is permitted by `scripts/check_licenses.py`.

This is an engineering compliance record, not legal advice. A legal owner must approve any later commercial distribution change that alters model weights, embeds new datasets, statically links copyleft code, or changes third-party terms.

## Development-only advisories

The complete npm tree currently reports 18 moderate advisories in development/tooling paths. None is present in the audited production closure, so none is classified as an unresolved production critical/high issue. Renovation work remains required when compatible upstream versions become available. CI continues to fail on high/critical production advisories.

## CI enforcement

The `security` CI job uses a full Git checkout, locked Node/Python versions, `npm ci --ignore-scripts`, production npm audit, pinned `pip-audit`, the repository-history secret scanner, and the license policy script. A failure blocks merge. Lockfile, manifest, or security-script changes require normal code review.
