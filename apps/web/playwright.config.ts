import {defineConfig} from '@playwright/test';
export default defineConfig({
  testDir:'./e2e', workers:1, retries:0, timeout:60000,
  use:{baseURL:process.env.STAFF_WEB_URL||'http://127.0.0.1:3000',headless:true,actionTimeout:10000,screenshot:"only-on-failure"},
});
