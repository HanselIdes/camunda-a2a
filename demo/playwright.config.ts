import { defineConfig } from '@playwright/test';

// The inspector URL and the agent URL come from run-demo.sh; the defaults match a local run.
export default defineConfig({
  testDir: './tests',
  timeout: 240_000,
  expect: { timeout: 200_000 },
  workers: 1,
  reporter: [['list']],
  outputDir: './artifacts',
  use: {
    baseURL: process.env.INSPECTOR_URL ?? 'http://127.0.0.1:5001',
    headless: process.env.HEADED ? false : true,
    viewport: { width: 1360, height: 900 },
    screenshot: 'only-on-failure',
    video: process.env.RECORD ? { mode: 'on', size: { width: 1360, height: 900 } } : 'off',
    launchOptions: { slowMo: process.env.HEADED || process.env.RECORD ? 400 : 0 },
  },
});
