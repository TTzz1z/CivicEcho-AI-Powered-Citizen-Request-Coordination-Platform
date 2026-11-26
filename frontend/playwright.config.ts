import { defineConfig, devices } from '@playwright/test'
export default defineConfig({
  testDir: './e2e', timeout: 60_000, fullyParallel: false, workers: 1, retries: process.env.CI ? 1 : 0,
  // Global setup pre-warms backend + orchestrator so the
  // first real E2E test doesn't pay the 4-8s cold-start cost.
  globalSetup: './e2e/global-setup.ts',
  outputDir: process.env.E2E_OUTPUT_DIR || './test-results',
  use: { baseURL: process.env.E2E_BASE_URL || 'http://127.0.0.1:8081', actionTimeout: 15_000, trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  projects: [
    // The smoke runner selects Chromium. Full regression can run all configured projects.
    { name: 'chromium', use: { ...devices['Desktop Chrome'], channel: process.env.E2E_CHROMIUM_CHANNEL } },
    { name: 'firefox', use: { ...devices['Desktop Firefox'] }, testIgnore: /smoke\.spec\.ts/ },
    { name: 'webkit', use: { ...devices['Desktop Safari'] }, testIgnore: /smoke\.spec\.ts/ },
  ],
})
