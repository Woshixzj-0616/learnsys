import assert from "node:assert/strict";
import { test } from "node:test";

import {
  bandText, bandWidth, formatMinutes, overallBand, trendBar,
} from "../js/pages/cet6/stats-format.js";

test("档位文本：空值显示破折号", () => {
  assert.equal(bandText(null), "—");
  assert.equal(bandText(undefined), "—");
  assert.equal(bandText("not-a-number"), "—");
  assert.equal(bandText(12), "12");
  assert.equal(bandText("7.5"), "7.5");
});

test("档位柱宽：按 15 档折算并封顶", () => {
  assert.equal(bandWidth(0), 0);
  assert.equal(bandWidth(9), 60);
  assert.equal(bandWidth(15), 100);
  assert.equal(bandWidth(20), 100);
  assert.equal(bandWidth(-3), 0);
  assert.equal(bandWidth("abc"), 0);
});

test("总平均档位按篇数加权，没有篇数返回 null", () => {
  assert.equal(overallBand({
    writing: { submissions: 2, avg_band: 12 },
    translation: { submissions: 1, avg_band: 6 },
  }), 10);
  assert.equal(overallBand({}), null);
  assert.equal(overallBand({
    writing: { submissions: 0, avg_band: 12 },
  }), null);
});

test("时长格式：不足一小时用分钟", () => {
  assert.equal(formatMinutes(0), "0 分钟");
  assert.equal(formatMinutes(59.6), "60 分钟");
  assert.equal(formatMinutes(60), "1.0 小时");
  assert.equal(formatMinutes(135), "2.3 小时");
});

test("趋势条：空值不着色，低档标红", () => {
  assert.deepEqual(trendBar(null), { text: "—", width: 0, level: "none" });
  assert.equal(trendBar(13).level, "high");
  assert.equal(trendBar(10).level, "mid");
  assert.equal(trendBar(9.9).level, "low");
  assert.equal(trendBar(7).width, 47);
});
