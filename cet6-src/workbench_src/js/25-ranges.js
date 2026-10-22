// @requires: 00-core.js
// 纯函数层：整段/整篇播放区间 + 「直接问」的结构化上下文。
// 不碰 DOM，方便用 node --test 直接测。
(function(WB){
  "use strict";

  function num(value, fallback){
    const n = Number(value);
    return isFinite(n) ? n : (fallback || 0);
  }

  function itemRange(item){
    if(!item) return {start:0, end:0};
    const content = item.content || {};
    const questions = item.questions || {};
    const start = Math.max(0, num(content.start) - 0.2);
    const contentEnd = Math.max(start + 0.2, num(content.end, start));
    const hasQuestions = num(questions.end) > num(questions.start) + 0.5;
    const end = hasQuestions ? num(questions.end) : contentEnd;
    return {start:start, end:Math.max(start + 0.2, end + 0.5)};
  }

  function sectionRange(sec){
    if(!sec) return {start:0, end:0};
    const start = Math.max(0, num(sec.start));
    const end = Math.max(start + 0.2, num(sec.end, start));
    return {start:start, end:end};
  }

  // 把当前学习现场压成一个 ContextSnapshot；服务端还会再做白名单和截断。
  // 除了当前句，还带前后句、本段原文、题目范围和进度，AI 才能回答
  // 「这段在讲什么」「为什么这句听不出来」而不只是看孤立一句。
  function contextPayload(input){
    input = input || {};
    const sentence = Number(input.sentence);
    const hasSentence = isFinite(sentence) && sentence >= 0;
    const errors = input.errors || {};
    const notes = input.notes || {};
    const stats = input.loopStats || {};
    const loop = hasSentence ? (stats[sentence] || {}) : {};
    const en = String(input.en || "").slice(0, 1000);
    const surrounding = {};
    if(hasSentence && en) surrounding.en = en;
    if(input.before) surrounding["前一句"] = String(input.before).slice(0, 1000);
    if(input.after) surrounding["后一句"] = String(input.after).slice(0, 1000);
    if(input.section) surrounding["Section"] = String(input.section).slice(0, 200);
    if(input.item) surrounding["题型单元"] = String(input.item).slice(0, 200);
    if(input.itemText) surrounding["本段原文"] = String(input.itemText).slice(0, 2000);
    if(input.questionText) surrounding["题目文本"] = String(input.questionText).slice(0, 1500);
    const learning = {
      sentence: hasSentence ? sentence : -1,
      display: input.display != null ? String(input.display).slice(0, 12) : "",
      en: en,
      tags: hasSentence ? (errors[sentence] || []) : [],
      note: hasSentence ? String(notes[sentence] || "").slice(0, 500) : "",
      loops: num(loop.loops),
      plays: num(loop.plays)
    };
    if(input.section) learning.section = String(input.section).slice(0, 200);
    if(input.item) learning.item = String(input.item).slice(0, 200);
    if(input.done != null) learning.done = !!input.done;
    if(input.paperDone != null) learning.paper_done = num(input.paperDone);
    if(input.paperTotal != null) learning.paper_total = num(input.paperTotal);
    return {
      surface: "cet6",
      object_type: "item",
      object_id: String(input.itemId || ""),
      title: String(input.title || "").slice(0, 200),
      selection: String(input.selection || "").slice(0, 2000),
      surrounding: surrounding,
      learning_state: learning,
      recent_actions: Array.isArray(input.recentActions)
        ? input.recentActions.slice(0, 20) : [],
      provenance: {
        source: "cet6",
        captured_at: new Date().toISOString(),
        ttl: 300
      }
    };
  }

  // 整卷句子时间轴：把每句的有效起点（含手动「设起点」）和下一句起点压平，
  // 供整段/整篇播放时查找「此刻在播哪一句」。纯函数，方便测试。
  function itemIdOf(sec, item){
    return (sec && sec.letter ? sec.letter : "?") + "-" + (item && item.index != null ? item.index : "?");
  }

  function sentenceTimeline(paper, startsByItem){
    const out = [];
    if(!paper || !Array.isArray(paper.sections)) return out;
    paper.sections.forEach(function(sec, si){
      (sec.items || []).forEach(function(item, ii){
        const map = (startsByItem || {})[itemIdOf(sec, item)] || {};
        const sents = item.sentences || [];
        sents.forEach(function(s, k){
          const manualStart = map[s.i];
          const start = manualStart != null ? num(manualStart) : num(s.start);
          const next = sents[k + 1];
          const nextManual = next && map[next.i] != null ? num(map[next.i]) : null;
          const nextStart = next ? (nextManual != null ? nextManual : num(next.start))
                                 : num(s.end) + 0.3;
          out.push({
            si: si, ii: ii, i: s.i,
            start: start,
            end: Math.max(start + 0.2, nextStart - 0.02),
            en: String(s.en || "")
          });
        });
      });
    });
    out.sort(function(a, b){ return a.start - b.start; });
    return out;
  }

  // 播放时间 t 落在哪一句；容忍首尾 0.35 秒，句间空隙不会来回闪。
  function sentenceAt(timeline, t){
    if(!Array.isArray(timeline) || !timeline.length) return null;
    const time = num(t);
    let lo = 0, hi = timeline.length - 1, best = -1;
    while(lo <= hi){
      const mid = (lo + hi) >> 1;
      if(timeline[mid].start <= time + 0.25){ best = mid; lo = mid + 1; }
      else hi = mid - 1;
    }
    if(best < 0) best = 0;
    // 先看「已经开始了的下一句」，避免句间 0.3 秒空隙还停在上句；
    // 下一句还没到起点时，再看上一句的尾巴。
    for(let k = Math.min(best, timeline.length - 1); k >= Math.max(0, best - 1); k--){
      const s = timeline[k];
      const startSlack = k === best ? 0.1 : 0.35;
      if(time >= s.start - startSlack && time <= s.end + 0.35) return s;
    }
    return null;
  }

  WB.ranges = {
    itemRange: itemRange,
    sectionRange: sectionRange,
    itemIdOf: itemIdOf,
    sentenceTimeline: sentenceTimeline,
    sentenceAt: sentenceAt
  };
  WB.contextPayload = contextPayload;
})(window.WB = window.WB || {});
