// TEST PATTERN: contract — browser renderer maps broker data without evaluating code.
import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const source = readFileSync(
  new URL("../../shared/widget-spec-renderer.js", import.meta.url),
  "utf8",
);

function loadRenderer() {
  const context = { window: {}, console };
  vm.runInNewContext(source, context);
  return context.window.gatewayWidgetSpec;
}

test("metric_sparkline has a fixed view model and ignores missing days", () => {
  const renderer = loadRenderer();
  const model = renderer.toViewModel({
    days: [
      { rate: 0.5 },
      { rate: null },
      { rate: 1 },
    ],
    summary: {
      rate: 0.75,
      caption: "近 3 天完成 3/4",
    },
  });

  assert.deepEqual(
    JSON.parse(JSON.stringify(model)),
    {
      metric: "75%",
      caption: "近 3 天完成 3/4",
      values: [0.5, null, 1],
    },
  );
  assert.equal(source.includes("eval("), false);
  assert.equal(source.includes("innerHTML"), false);
});

test("memo_list maps the broker-owned GUI contract", () => {
  const renderer = loadRenderer();
  const model = renderer.toMemoViewModel({
    caption: "后台 AI 唤醒尚未启用",
    items: [{
      occurrence_id: "occ-1",
      series_id: "series-1",
      text: "晚上跑步",
      due_at: "2026-07-28T20:00:00+08:00",
      state: "pending",
      overdue: true,
      schedule: { kind: "weekly", weekdays: [2] },
      schedule_label: "每周 1、3、5",
      notification_enabled: false,
      secret: "ignored",
    }],
  });
  assert.deepEqual(JSON.parse(JSON.stringify(model)), {
    caption: "后台 AI 唤醒尚未启用",
    items: [{
      occurrenceId: "occ-1",
      seriesId: "series-1",
      text: "晚上跑步",
      dueAt: "2026-07-28T20:00:00+08:00",
      state: "pending",
      overdue: true,
      schedule: { kind: "weekly", weekdays: [2] },
      scheduleLabel: "每周 1、3、5",
      notificationEnabled: false,
    }],
  });
  assert.equal(source.includes("/api/memos"), true);
  assert.equal(source.includes("gateway:ai-intent"), true);
});

test("memo date fields reject normalized invalid dates", () => {
  const renderer = loadRenderer();
  assert.equal(renderer.memoIsoFromFields("2026-02-30", "09:30"), "");
  assert.equal(renderer.memoIsoFromFields("2026-08-11", "25:00"), "");

  const value = renderer.memoIsoFromFields("2026-08-11", "09:30");
  assert.notEqual(value, "");
  assert.deepEqual(
    JSON.parse(JSON.stringify(renderer.memoFieldsFromIso(value))),
    { date: "2026-08-11", time: "09:30" },
  );
});
