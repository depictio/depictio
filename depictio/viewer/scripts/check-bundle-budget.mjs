#!/usr/bin/env node
/**
 * Bundle byte-budget guard (serverless RFC §10: "bundle bloat is the failure
 * mode that silently ruins single-file").
 *
 *   node scripts/check-bundle-budget.mjs <file> <gzip-budget-bytes> [label]
 *
 * Fails (exit 1) when the gzipped size exceeds the budget; warns on stderr
 * when it crosses 90% of it. Budgets live in the CI workflow so a bump is a
 * reviewable diff there, not a silent constant change here.
 */
import { readFileSync } from 'node:fs';
import { gzipSync } from 'node:zlib';

const [, , file, budgetArg, label = file] = process.argv;
if (!file || !budgetArg) {
  console.error('usage: check-bundle-budget.mjs <file> <gzip-budget-bytes> [label]');
  process.exit(2);
}
const budget = Number(budgetArg);
if (!Number.isFinite(budget) || budget <= 0) {
  console.error(`invalid budget "${budgetArg}"`);
  process.exit(2);
}

const raw = readFileSync(file);
const gzipped = gzipSync(raw, { level: 9 }).length;
const mb = (n) => `${(n / 1024 / 1024).toFixed(2)} MB`;
const pct = ((gzipped / budget) * 100).toFixed(1);

console.log(`${label}: raw ${mb(raw.length)}, gzip ${mb(gzipped)} — ${pct}% of the ${mb(budget)} budget`);

if (gzipped > budget) {
  console.error(
    `FAIL: gzip size ${mb(gzipped)} exceeds the ${mb(budget)} budget. ` +
      'Either trim the bundle (check the dedupe list and new dependencies) or ' +
      'raise the budget deliberately in .github/workflows/serverless-ci.yaml.',
  );
  process.exit(1);
}
if (gzipped > budget * 0.9) {
  console.error(`WARN: gzip size is above 90% of the budget — headroom is nearly gone.`);
}
