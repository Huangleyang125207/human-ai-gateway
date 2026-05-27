// E2E: AI 在 chat 返的图 → 缩略图,点击开 lightbox 看大图。
// 跟 server / shared 本体分开 —— 这里只测行为,不掺production 逻辑。
//
// 跑法(用系统 Chrome,不下 Playwright 自带的 ~150MB Chromium):
//   cd gateway/tests/e2e && npm i -D @playwright/test    # 只装小包,无浏览器
//   先起 gateway: GATEWAY_NO_OPEN=1 python server.py     (或已有实例在 4321)
//   再跑:        npx playwright test                      # config 里 channel:'chrome' 用系统 Chrome
//
// 注:断言用结构态(display / .on class / 尺寸),不断言 computed opacity
//     —— headless 不推进 CSS transition,opacity 读数不可靠。
import { test, expect } from "@playwright/test";

const BASE = process.env.GATEWAY_URL || "http://127.0.0.1:4321";
// 一张确定存在的历史上传图(backfill 后索引里有)
const TEST_IMG = "/attachments/2026-05-24/192116-06812d.jpg";

test.beforeEach(async ({ page }) => {
  await page.goto(BASE + "/");
  await page.waitForTimeout(1200); // 等 thread.js 初始化
});

test("AI 返图在 chat 里是缩略图(尺寸受限)", async ({ page }) => {
  await page.evaluate((src) => {
    const stream = document.getElementById("threadStream");
    const el = document.createElement("div");
    el.className = "t-msg ai";
    el.innerHTML = `<span class="who">AI</span><div class="body"><img src="${src}" alt=""></div>`;
    stream.appendChild(el);
  }, TEST_IMG);

  const img = page.locator("#threadStream .body img").last();
  await expect(img).toBeVisible();
  const box = await img.boundingBox();
  expect(box.width).toBeLessThanOrEqual(180);
  expect(box.height).toBeLessThanOrEqual(180);
  await expect(img).toHaveCSS("cursor", "zoom-in");
});

test("点击缩略图 → 开 lightbox 看大图,再点关闭", async ({ page }) => {
  await page.evaluate((src) => {
    const stream = document.getElementById("threadStream");
    const el = document.createElement("div");
    el.className = "t-msg ai";
    el.innerHTML = `<span class="who">AI</span><div class="body"><img src="${src}" alt=""></div>`;
    stream.appendChild(el);
  }, TEST_IMG);

  await page.locator("#threadStream .body img").last().click();

  const lb = page.locator("#imgLightbox");
  await expect(lb).toHaveClass(/\bon\b/);            // .on 可靠加上(reflow 触发,非 rAF)
  await expect(lb).toHaveCSS("display", "flex");

  const lbImg = lb.locator("img");
  const box = await lbImg.boundingBox();
  expect(box.width).toBeGreaterThan(180);            // 大图比缩略图大

  // 点 lightbox 任意处关闭
  await lb.click();
  await page.waitForTimeout(250);
  await expect(lb).not.toHaveClass(/\bon\b/);
});
