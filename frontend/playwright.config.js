var __assign = (this && this.__assign) || function () {
    __assign = Object.assign || function(t) {
        for (var s, i = 1, n = arguments.length; i < n; i++) {
            s = arguments[i];
            for (var p in s) if (Object.prototype.hasOwnProperty.call(s, p))
                t[p] = s[p];
        }
        return t;
    };
    return __assign.apply(this, arguments);
};
import { defineConfig, devices } from '@playwright/test';
export default defineConfig({
    testDir: './e2e', timeout: 60000, fullyParallel: false, workers: 1, retries: process.env.CI ? 1 : 0,
    // Round 2 r2-9: global setup pre-warms Rasa + backend + orchestrator so the
    // first real E2E test doesn't pay the 4-8s cold-start cost (root cause #4/#8).
    globalSetup: './e2e/global-setup.ts',
    use: { baseURL: process.env.E2E_BASE_URL || 'http://localhost:8081', trace: 'retain-on-failure', screenshot: 'only-on-failure' },
    projects: [
        // R5: default to chromium only for daily runs (Smoke tests).
        // Use --project=firefox / --project=webkit explicitly for full regression.
        { name: 'chromium', use: __assign({}, devices['Desktop Chrome']) },
        { name: 'firefox', use: __assign({}, devices['Desktop Firefox']), testIgnore: /smoke\.spec\.ts/ },
        { name: 'webkit', use: __assign({}, devices['Desktop Safari']), testIgnore: /smoke\.spec\.ts/ },
    ],
});
