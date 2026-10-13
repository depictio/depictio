import { defineConfig } from 'vitest/config';

// Unit tests here cover pure logic only (newick parsing, subtree/selection
// helpers) — node environment, no jsdom, no React/Plotly. Anything that needs
// a DOM belongs in the Playwright suite (depictio/tests/e2e-playwright).
export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
});
