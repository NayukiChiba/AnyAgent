import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  testMatch: '*.spec.js',
  workers: 1,
  use: {
    baseURL: 'http://127.0.0.1:18765',
    browserName: 'chromium',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: 'uv run python -m tests.e2e_server',
    cwd: '..',
    url: 'http://127.0.0.1:18765/health/ready',
    reuseExistingServer: false,
    timeout: 30000,
  },
})
