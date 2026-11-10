import assert from "node:assert/strict";
import { test } from "node:test";

import { legacyEnglishHash } from "../js/legacy-routes.js";

test("旧 #/cet6 各 tab 映射到英语聚合页", () => {
  assert.equal(legacyEnglishHash("cet6", ""), "#/english?tab=listening");
  assert.equal(legacyEnglishHash("cet6", "tab=writing"),
               "#/english?tab=writing&sub=writing");
  assert.equal(legacyEnglishHash("cet6", "tab=translation"),
               "#/english?tab=writing&sub=translation");
  assert.equal(legacyEnglishHash("cet6", "tab=review"),
               "#/english?tab=review");
  assert.equal(legacyEnglishHash("cet6", "tab=stats"),
               "#/english?tab=stats");
  assert.equal(legacyEnglishHash("cet6", "tab=drill"),
               "#/english?tab=listening");
});

test("断点 / 二稿 / 技能参数原样带到新页", () => {
  assert.equal(legacyEnglishHash("cet6", "paper=paper-3"),
               "#/english?tab=listening&paper=paper-3");
  assert.equal(legacyEnglishHash("cet6", "tab=writing&submission=15&rewrite=1"),
               "#/english?tab=writing&sub=writing&submission=15&rewrite=1");
  assert.equal(legacyEnglishHash("cet6", "tab=translation&skill=%E6%96%87%E5%8C%96%E6%9C%AF%E8%AF%AD"),
               "#/english?tab=writing&sub=translation&skill=%E6%96%87%E5%8C%96%E6%9C%AF%E8%AF%AD");
});

test("其他页面不重定向", () => {
  assert.equal(legacyEnglishHash("today", "tab=writing"), "");
  assert.equal(legacyEnglishHash("english", "tab=stats"), "");
});
