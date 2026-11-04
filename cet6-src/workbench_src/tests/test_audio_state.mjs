// 播放状态机测试：暂停/继续、单句窗口与全局控件的边界。
// 运行：node --test D:\cet6_tool\workbench_src\tests\test_audio_state.mjs
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const js = path.join(here, "..", "js");

function classList() {
  const set = new Set();
  return {
    add(c) { set.add(c); },
    remove(c) { set.delete(c); },
    toggle(c, on) {
      if (on === undefined) set.has(c) ? set.delete(c) : set.add(c);
      else if (on) set.add(c);
      else set.delete(c);
    },
    contains(c) { return set.has(c); },
  };
}

function setup() {
  const listeners = {};
  const audio = {
    paused: true, currentTime: 0, duration: 100, playbackRate: 1,
    readyState: 4, src: "audio.mp3",
    addEventListener(name, fn) { (listeners[name] ||= []).push(fn); },
    fire(name) { for (const fn of listeners[name] || []) fn(); },
    play() { this.paused = false; this.fire("play"); return Promise.resolve(); },
    pause() { const was = this.paused; this.paused = true; if (!was) this.fire("pause"); },
  };
  const cards = [1, 2, 3].map((i) => ({
    dataset: { i: String(i) },
    classList: classList(),
    scrollIntoView() {},
  }));
  const document = {
    querySelectorAll(sel) {
      if (sel === ".card") return cards;
      if (sel === ".card.follow") return cards.filter((c) => c.classList.contains("follow"));
      if (sel === ".card.playing, .card.active") {
        return cards.filter((c) => c.classList.contains("playing") || c.classList.contains("active"));
      }
      return [];
    },
    querySelector(sel) {
      const m = /\.card\[data-i="(\d+)"\]/.exec(sel);
      if (m) return cards.find((c) => c.dataset.i === m[1]) || null;
      if (sel === ".card") return cards[0] || null;
      return null;
    },
  };
  const timers = new Map();
  let nextTimer = 1;
  const sandbox = {
    window: { addEventListener() {} },
    document,
    console,
    setInterval(fn) { const id = nextTimer++; timers.set(id, fn); return id; },
    clearInterval(id) { timers.delete(id); },
  };
  vm.createContext(sandbox);
  for (const name of ["00-core.js", "25-ranges.js", "30-audio.js"]) {
    vm.runInContext(fs.readFileSync(path.join(js, name), "utf8"), sandbox);
  }
  const WB = sandbox.window.WB;
  const sec = {
    letter: "A", name: "Section A", start: 0, end: 60,
    items: [{
      index: 1, title: "Passage 1",
      content: { start: 10, end: 40 },
      questions: { start: 41, end: 50 },
      sentences: [
        { i: 1, start: 10, end: 14, en: "a" },
        { i: 2, start: 14.5, end: 19, en: "b" },
        { i: 3, start: 19.5, end: 24, en: "c" },
      ],
    }],
  };
  const paper = { title: "测试卷", sections: [sec] };
  const item = sec.items[0];

  WB.dom = {
    audio,
    playPauseBtn: { textContent: "", setAttribute() {}, addEventListener() {} },
    playerSeek: { value: "0", addEventListener() {} },
    playerCur: { textContent: "" },
    playerDur: { textContent: "" },
    playerRateBadge: { textContent: "" },
  };
  WB.render = { sentenceBar() {}, miniPlayer() {} };
  WB.status = () => {};
  WB.store = { loadRate() { return 1; }, saveRate() {} };
  WB.state = { starts: {} };
  WB.session.paper = paper;
  WB.session.currentSi = 0;
  WB.session.currentIi = 0;
  WB.session.playRate = 1;
  const bumps = [];
  WB.paper = {
    currentSection() { return sec; },
    currentItem() { return item; },
    baseRangeByIndex(i) {
      const idx = item.sentences.findIndex((s) => s.i === i);
      if (idx < 0) return null;
      const s = item.sentences[idx];
      const next = item.sentences[idx + 1];
      const start = Math.max(0, s.start - 0.15);
      let end = next ? next.start - 0.02 : s.end + 0.3;
      if (end <= start) end = start + 1.5;
      return [start, end];
    },
    resolveAB() { return { a: null, b: null, mode: null }; },
    loopCfgFor() { return { on: false, times: 1 }; },
    bumpLoopStat(i, key) {
      bumps.push([i, key]);
      return { plays: 1, loops: 1 };
    },
  };
  WB.audio.init();
  WB.audio.onTick = () => {};
  WB.audio.onWindowChange = () => {};
  WB.audio.onLoopStat = () => {};

  return {
    WB, audio, cards, bumps,
    S: WB.session,
    timers,
    tick() { for (const fn of [...timers.values()]) fn(); },
  };
}

test("整段播放中暂停再继续：边界定时器恢复，跟随继续推进", () => {
  const { WB, audio, S, timers } = setup();
  WB.audio.playItem();
  assert.equal(audio.paused, false);
  assert.equal(timers.size, 1, "整段播放应有边界定时器");

  audio.currentTime = 12;
  audio.fire("timeupdate");
  assert.equal(S.followIndex, 1);

  WB.audio.togglePlayPause();
  assert.equal(audio.paused, true);
  assert.equal(timers.size, 0, "暂停应停掉定时器");

  WB.audio.togglePlayPause();
  assert.equal(audio.paused, false);
  assert.equal(timers.size, 1, "继续播放后定时器必须恢复");

  audio.currentTime = 15;
  audio.fire("timeupdate");
  assert.equal(S.followIndex, 2, "继续播放后跟随不能冻住");
});

test("单句暂停后拖全局进度条：退出单句，播放从新位置继续", () => {
  const { WB, audio, S } = setup();
  WB.audio.playSentence(2);
  assert.equal(S.activeSentence, 2);
  WB.audio.togglePlayPause();
  assert.equal(audio.paused, true);

  WB.audio.seekToFraction(0.5);
  assert.equal(audio.currentTime, 50);
  assert.equal(S.activeSentence, -1);
  assert.equal(S.rangeEnd, 0);
  assert.equal(S.followActive, true);

  WB.audio.togglePlayPause();
  assert.equal(audio.paused, false);
  assert.equal(audio.currentTime, 50, "按播放不能跳回上一句");
});

test("整段播放中拖单句滑块：只移动播放头，不缩小整段窗口", () => {
  const { WB, audio, S } = setup();
  WB.audio.playItem();
  const end = S.rangeEnd;
  WB.audio.seekFraction(3, 500);
  assert.equal(S.rangeEnd, end, "整段窗口不能被缩成单句");
  assert.equal(S.activeSentence, -1);
  assert.ok(Math.abs(audio.currentTime - 21.825) < 1e-6);
});

test("单句自然播完：撤掉窗口，下次播放从当前位置继续", () => {
  const { WB, audio, S, tick } = setup();
  WB.audio.playSentence(3);
  const boundary = S.rangeEnd;
  audio.currentTime = boundary;
  tick();

  assert.equal(audio.paused, true);
  assert.equal(S.activeSentence, -1);
  assert.equal(S.rangeEnd, 0);

  WB.audio.togglePlayPause();
  assert.equal(audio.paused, false);
  assert.equal(audio.currentTime, boundary, "不应跳回句首");
});

test("整段播放中把全局进度条拖出区间：不立即暂停", () => {
  const { WB, audio, S, timers, tick } = setup();
  WB.audio.playItem();
  WB.audio.seekToFraction(0.8);
  assert.equal(audio.currentTime, 80);
  assert.equal(S.rangeEnd, 0, "拖出区间后撤掉整段窗口");
  assert.equal(audio.paused, false);
  assert.equal(timers.size, 0);
  tick();
  assert.equal(audio.paused, false);
});

function loopCount(bumps, i) {
  return bumps.filter(([idx, key]) => idx === i && key === "loops").length;
}

test("单句听到一半把小滑块拖回句首：记一次回听，单句窗口保留", () => {
  const { WB, audio, S, bumps } = setup();
  WB.audio.playSentence(2);
  audio.currentTime = 17;            // 已经听过一句的一半
  audio.fire("timeupdate");

  WB.audio.seekFraction(2, 0);       // 拖回句首
  assert.equal(loopCount(bumps, 2), 1);
  assert.equal(S.activeSentence, 2, "不能丢掉单句窗口");
});

test("一次拖动连续触发 input：只记一次回听", () => {
  const { WB, audio, bumps } = setup();
  WB.audio.playSentence(2);
  audio.currentTime = 17;
  audio.fire("timeupdate");

  for (let v = 500; v >= 0; v -= 100) WB.audio.seekFraction(2, v);
  assert.equal(loopCount(bumps, 2), 1, "拖动的中间事件不能重复计数");
});

test("句内小幅回拉（没回到句首）：不算回听", () => {
  const { WB, audio, bumps } = setup();
  WB.audio.playSentence(2);
  audio.currentTime = 18;
  audio.fire("timeupdate");

  WB.audio.seekFraction(2, 300);     // 从 80% 回拉到 30%
  assert.equal(loopCount(bumps, 2), 0);
});

test("全局进度条拖回当前句内部：保留单句，不退出", () => {
  const { WB } = setup();
  WB.audio.playSentence(2);
  const start = WB.session.rangeStart;
  const end = WB.session.rangeEnd;

  WB.audio.seekToFraction((start + (end - start) * 0.5) / 100);
  assert.equal(WB.session.activeSentence, 2);
  assert.equal(WB.session.rangeStart, start);
  assert.equal(WB.session.rangeEnd, end);
});

test("自动循环回绕只记一次，不和回听判定重复", () => {
  const { WB, audio, S, bumps, tick } = setup();
  WB.paper.loopCfgFor = () => ({ on: true, times: 1 });
  WB.audio.playSentence(2);
  const before = loopCount(bumps, 2);

  audio.currentTime = S.rangeEnd;
  tick();
  assert.equal(loopCount(bumps, 2) - before, 1);
});
