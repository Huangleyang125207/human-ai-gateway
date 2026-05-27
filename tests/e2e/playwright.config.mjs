// Playwright e2e 配置 — 用系统 Chrome,不下 Playwright 自带 Chromium(省 ~150MB)。
// 只测本地 gateway UI,不需要 pin 死浏览器版本的确定性。
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: ".",
  timeout: 30_000,
  use: {
    channel: "chrome",          // 系统 Chrome,零浏览器下载
    headless: true,
    baseURL: process.env.GATEWAY_URL || "http://127.0.0.1:4321",
  },
});
