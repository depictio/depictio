import { defineConfig } from 'vitest/config';

// Pure logic only (SSE framing, the agent-run trace reducer, thread filters):
// node environment, no DOM, no React. UI states belong in Playwright.
export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
});
