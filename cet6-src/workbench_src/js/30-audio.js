// @requires: 00-core.js, 10-storage.js, 20-paper.js
// 服务层：音频播放状态机。这里集中管理 audio 元素、边界定时器、循环/连播和 A-B 窗口。
(function(WB){
  "use strict";

  const U = WB.util;
  let audio = null;
  let inited = false;
  let timelineCache = null;
  let seeking = false;

  function S(){ return WB.session; }

  function notifyTick(){
    if(audio){
      updateFollow();
      updatePlayerUI();
    }
    if(WB.audio.onTick) WB.audio.onTick();
  }
  function notifyWindow(){ if(WB.audio.onWindowChange) WB.audio.onWindowChange(); }
  function notifyRate(){ if(WB.audio.onRateChange) WB.audio.onRateChange(); }
  function notifyLoop(i, st){ if(WB.audio.onLoopStat) WB.audio.onLoopStat(i, st); }

  function safePlay(){
    const p = audio.play();
    if(p && p.catch) p.catch(function(){});
  }

  function url(path){
    if(/^(https?:|file:|data:|\/)/i.test(path)) return path;
    return S().audioBase + path;
  }

  // 把某句解析成实际播放窗口：A-B 优先，其次只有 A，最后整句。
  function resolveWindow(i){
    const base = WB.paper.baseRangeByIndex(i);
    if(!base) return null;
    const ab = WB.paper.resolveAB(i);
    if(ab.mode === "ab"){
      return {start:ab.a, end:ab.b, mode:"ab", baseStart:base[0], baseEnd:base[1]};
    }
    if(ab.mode === "a"){
      return {start:ab.a, end:base[1], mode:"a", baseStart:base[0], baseEnd:base[1]};
    }
    return {start:base[0], end:base[1], mode:"normal", baseStart:base[0], baseEnd:base[1]};
  }

  function bumpLoops(i){
    const st = WB.paper.bumpLoopStat(i, "loops");
    notifyLoop(i, st);
  }

  // ---- 整段/整篇播放跟随：按时间找当前句 ----
  function timeline(){
    if(!timelineCache){
      timelineCache = WB.ranges.sentenceTimeline(S().paper, (WB.state && WB.state.starts) || {});
    }
    return timelineCache;
  }

  function invalidateTimeline(){
    timelineCache = null;
  }

  function clearFollowHighlight(){
    document.querySelectorAll(".card.follow").forEach(function(c){
      c.classList.remove("follow");
    });
    S().followIndex = -1;
  }

  // 撤掉当前播放区间（单句 / 整段 / 题目），播放头留在原处。
  // 用在两处：全局控件（进度条、播放键、← →）接管时；一段自然播完时。
  // 之后按整轨跟随，下一次播放从当前位置继续，不会卡回上一句。
  function releaseRange(){
    stopBoundaryTimer();
    S().activeSentence = -1;
    S().rangeStart = 0;
    S().rangeEnd = 0;
    S().repeatLeft = 0;
    S().activeLoopCfg = {on:false, times:1};
    S().ab = null;
    document.querySelectorAll(".card.playing, .card.active").forEach(function(c){
      c.classList.remove("playing");
      c.classList.remove("active");
    });
    S().followActive = true;
    S().followScope = "paper";
    S().followPaused = false;
  }

  function followScopeHit(hit){
    if(!hit) return false;
    if(S().followScope === "item"){
      return hit.si === S().currentSi && hit.ii === S().currentIi;
    }
    if(S().followScope === "section"){
      return hit.si === S().followSectionSi;
    }
    return true;
  }

  function updateFollow(){
    if(!S().followActive) return;
    const hit = WB.ranges.sentenceAt(timeline(), audio.currentTime);
    if(!hit || !followScopeHit(hit)){
      // 句间空隙 / 题目段：保留上一个高亮，不要一秒一闪。
      return;
    }
    if(hit.si !== S().currentSi || hit.ii !== S().currentIi){
      if(WB.audio.onFollowItem){
        WB.audio.onFollowItem(hit.si, hit.ii, hit.i);
      }
    }
    if(hit.i === S().followIndex) return;
    clearFollowHighlight();
    S().followIndex = hit.i;
    const card = document.querySelector('.card[data-i="' + hit.i + '"]');
    if(card){
      card.classList.add("follow");
      if(!S().followPaused){
        card.scrollIntoView({block:"center", behavior:"smooth"});
      }
    }
    if(WB.render && WB.render.sentenceBar) WB.render.sentenceBar();
  }

  function setFollowPaused(paused){
    S().followPaused = !!paused;
    if(!S().followPaused && S().followIndex >= 0){
      const card = document.querySelector('.card[data-i="' + S().followIndex + '"]');
      if(card) card.scrollIntoView({block:"center", behavior:"smooth"});
    }
    if(WB.render && WB.render.sentenceBar) WB.render.sentenceBar();
  }

  function seekBy(delta){
    if(!audio) return;
    const dur = Number(audio.duration);
    const max = isFinite(dur) && dur > 0 ? dur : 1e9;
    const t = U.clamp(audio.currentTime + Number(delta || 0), 0, max);
    audio.currentTime = t;
    // 单句模式下挪出这一句的范围，就退出单句，别再让下一次播放跳回去。
    if(S().activeSentence >= 0){
      const win = resolveWindow(S().activeSentence);
      if(win && (t < win.start - 0.05 || t >= win.end - 0.05)) releaseRange();
    }
    if(S().followActive) S().followPaused = false;
    updateFollow();
    notifyTick();
  }

  // 自绘播放条：原生 controls 的左右键会按整段音频比例跳（28 分钟能跳 17 秒），
  // 精听不能用，所以只保留 audio 元素，控件全部自己做。
  function updatePlayerUI(){
    if(!audio) return;
    const dur = Number(audio.duration);
    const total = isFinite(dur) && dur > 0 ? dur : 0;
    const cur = Math.max(0, Number(audio.currentTime) || 0);
    if(WB.dom.playerCur) WB.dom.playerCur.textContent = U.fmtMini(cur);
    if(WB.dom.playerDur) WB.dom.playerDur.textContent = total ? U.fmtMini(total) : "0:00";
    if(WB.dom.playerSeek && !seeking){
      WB.dom.playerSeek.value = total
        ? String(Math.round(U.clamp(cur / total, 0, 1) * 1000))
        : "0";
    }
    if(WB.dom.playPauseBtn){
      WB.dom.playPauseBtn.textContent = audio.paused ? "▶" : "❚❚";
      WB.dom.playPauseBtn.setAttribute("aria-label", audio.paused ? "播放" : "暂停");
    }
  }

  function seekToFraction(frac){
    if(!audio) return;
    const dur = Number(audio.duration);
    if(!isFinite(dur) || dur <= 0) return;
    const t = U.clamp(Number(frac) || 0, 0, 1) * dur;
    // 全局进度条是整轨控制：单句窗口一律让路；整段窗口只在跳出去时让路。
    if(S().activeSentence >= 0 ||
       (S().rangeEnd > S().rangeStart && (t < S().rangeStart || t > S().rangeEnd))){
      releaseRange();
    }
    audio.currentTime = t;
    if(S().followActive) S().followPaused = false;
    updateFollow();
    notifyTick();
  }

  function togglePlayPause(){
    if(!audio) return;
    if(!audio.paused){
      audio.pause();
      return;
    }
    const i = S().activeSentence;
    if(i >= 0){
      const win = resolveWindow(i);
      const inside = win &&
        audio.currentTime >= win.start - 0.05 && audio.currentTime < win.end - 0.05;
      if(inside){
        // 暂停在句内：继续这一句（循环 / 连播设置照旧生效）
        safePlay();
        startBoundaryTimer();
        notifyTick();
        return;
      }
      // 播放头已经不在这一句里（拖过进度条等）：退出单句，从当前位置继续。
      releaseRange();
    }
    safePlay();
    notifyTick();
  }

  function playRange(start, end, sentenceIndex, scope){
    let win = null;
    if(sentenceIndex != null){
      win = resolveWindow(sentenceIndex);
      if(!win) return;
      start = win.start;
      end = win.end;
    }
    S().rangeStart = Math.max(0, start);
    S().rangeEnd = Math.max(S().rangeStart + 0.2, end);
    S().activeSentence = (sentenceIndex == null) ? -1 : sentenceIndex;

    if(sentenceIndex != null){
      S().activeLoopCfg = WB.paper.loopCfgFor(sentenceIndex);
      S().repeatLeft = S().activeLoopCfg.on
        ? 0
        : Math.max(0, S().activeLoopCfg.times - 1);
      S().ab = (win.mode === "ab")
        ? {a:S().rangeStart, b:S().rangeEnd}
        : null;
      const st = WB.paper.bumpLoopStat(sentenceIndex, "plays");
      notifyLoop(sentenceIndex, st);
      S().followActive = false;
      S().followPaused = false;
      clearFollowHighlight();
    }else{
      S().activeLoopCfg = {on:false, times:1};
      S().repeatLeft = 0;
      S().ab = null;
      document.querySelectorAll(".card.playing, .card.active").forEach(function(c){
        c.classList.remove("playing");
        c.classList.remove("active");
      });
      // 无单句的区间播放（整段/正文/整篇）= 开启跟随；题目段由调用方关掉。
      if(!scope || scope.kind !== "questions"){
        S().followActive = true;
        S().followScope = (scope && scope.kind) || "item";
        S().followSectionSi = (scope && scope.si != null) ? scope.si : S().currentSi;
        S().followPaused = false;
        clearFollowHighlight();
      }else{
        S().followActive = false;
        clearFollowHighlight();
      }
    }
    notifyWindow();

    const go = function(){
      audio.currentTime = S().rangeStart;
      safePlay();
      startBoundaryTimer();
      updateFollow();
      notifyTick();
    };
    if(audio.readyState >= 1) go();
    else audio.addEventListener("loadedmetadata", go, {once:true});
  }

  function checkBoundary(){
    if(!S().rangeEnd) return;
    const ab = S().ab;
    const boundary = ab ? ab.b : S().rangeEnd;
    if(audio.currentTime >= boundary){
      if(ab){
        audio.currentTime = ab.a;
        safePlay();
        bumpLoops(S().activeSentence);
      }else if(S().activeLoopCfg.on){
        audio.currentTime = S().rangeStart;
        safePlay();
        bumpLoops(S().activeSentence);
      }else if(S().repeatLeft > 0){
        S().repeatLeft -= 1;
        audio.currentTime = S().rangeStart;
        safePlay();
        bumpLoops(S().activeSentence);
      }else{
        // 这一句/这一段自然播完：撤掉区间，下一次播放从当前位置接着走。
        audio.pause();
        stopBoundaryTimer();
        releaseRange();
        notifyWindow();
      }
      notifyTick();
    }else{
      notifyTick();
    }
  }

  function startBoundaryTimer(){
    if(S().boundaryTimer) return;
    S().boundaryTimer = setInterval(checkBoundary, 50);
  }

  function stopBoundaryTimer(){
    if(S().boundaryTimer){
      clearInterval(S().boundaryTimer);
      S().boundaryTimer = null;
    }
  }

  function playSentence(i){
    const win = resolveWindow(i);
    if(!win) return;
    document.querySelectorAll(".card").forEach(function(c){
      c.classList.toggle("playing", c.dataset.i === String(i));
    });
    playRange(win.start, win.end, i);
  }

  function toggleSentence(i){
    const win = resolveWindow(i);
    if(!win) return;
    if(S().activeSentence === i && !audio.paused){
      audio.pause();
      notifyTick();
      return;
    }
    if(S().activeSentence === i && audio.paused &&
       audio.currentTime >= win.start && audio.currentTime < win.end - 0.05){
      safePlay();
      startBoundaryTimer();
      notifyTick();
      return;
    }
    playSentence(i);
  }

  function seekFraction(i, value){
    const activeHere = (i === S().activeSentence);
    // 整段/整篇跟随中拖单句滑块：只移动播放头，不把整段窗口缩成一句。
    if(!activeHere && S().followActive){
      const base = WB.paper.baseRangeByIndex(i);
      if(!base) return;
      audio.currentTime = base[0] + (Number(value) / 1000) * (base[1] - base[0]);
      S().followPaused = false;
      updateFollow();
      notifyTick();
      return;
    }
    const win = (activeHere && S().rangeEnd > S().rangeStart)
      ? {start:S().rangeStart, end:S().rangeEnd, mode:(S().ab ? "ab" : "normal")}
      : resolveWindow(i);
    if(!win) return;
    S().activeSentence = i;
    S().rangeStart = win.start;
    S().rangeEnd = win.end;
    S().ab = (win.mode === "ab") ? {a:win.start, b:win.end} : null;
    audio.currentTime = win.start + (Number(value) / 1000) * (win.end - win.start);
    notifyWindow();
    notifyTick();
  }

  function focusSentence(i){
    const win = resolveWindow(i);
    if(!win) return;
    S().followActive = false;
    S().followPaused = false;
    clearFollowHighlight();
    S().activeSentence = i;
    S().rangeStart = win.start;
    S().rangeEnd = win.end;
    S().ab = (win.mode === "ab") ? {a:win.start, b:win.end} : null;
    audio.pause();
    stopBoundaryTimer();
    audio.currentTime = win.start;
    document.querySelectorAll(".card").forEach(function(c){
      c.classList.toggle("active", c.dataset.i === String(i));
    });
    const card = document.querySelector('.card[data-i="' + i + '"]');
    if(card) card.scrollIntoView({block:"center", behavior:"smooth"});
    notifyWindow();
    notifyTick();
  }

  function moveSentence(delta){
    const item = WB.paper.currentItem();
    if(!item || !item.sentences.length) return;
    let idx = item.sentences.findIndex(function(s){ return s.i === S().activeSentence; });
    if(idx < 0) idx = 0;
    else idx = Math.max(0, Math.min(item.sentences.length - 1, idx + delta));
    focusSentence(item.sentences[idx].i);
  }

  function replayActive(){
    let i = S().activeSentence;
    // 整段/整篇跟随中按 R：重播正在跟的那一句，而不是第一句。
    if(i < 0 && S().followActive && S().followIndex >= 0) i = S().followIndex;
    if(i < 0){
      const card = document.querySelector(".card");
      i = card ? Number(card.dataset.i) : -1;
    }
    if(i >= 0) playSentence(i);
  }

  function jumpToStart(){
    const item = WB.paper.currentItem();
    audio.pause();
    stopBoundaryTimer();
    S().activeSentence = -1;
    S().rangeEnd = 0;
    S().ab = null;
    S().followActive = false;
    S().followPaused = false;
    clearFollowHighlight();
    document.querySelectorAll(".card.playing, .card.active").forEach(function(c){
      c.classList.remove("playing");
      c.classList.remove("active");
    });
    audio.currentTime = Math.max(0, item.content.start - 0.2);
    notifyWindow();
    notifyTick();
  }

  function playContent(){
    const item = WB.paper.currentItem();
    playRange(Math.max(0, item.content.start - 0.2), item.content.end + 0.2, null,
      {kind:"item", si:S().currentSi, ii:S().currentIi});
  }

  // 整段 = 正文 + 题目；整篇 = 当前 Section。都不绑定单句，但会跟随当前句。
  function playItem(){
    const item = WB.paper.currentItem();
    if(!item) return;
    const r = WB.ranges.itemRange(item);
    playRange(r.start, r.end, null, {kind:"item", si:S().currentSi, ii:S().currentIi});
    WB.status("正在播放整段：正文 + 题目（界面会跟着当前句滚动）");
  }

  function playSection(){
    const sec = WB.paper.currentSection();
    if(!sec) return;
    const r = WB.ranges.sectionRange(sec);
    playRange(r.start, r.end, null, {kind:"section", si:S().currentSi});
    WB.status("正在播放整个 " + sec.name + "（界面会跟着当前句滚动）");
  }

  function stopPlayback(){
    audio.pause();
    stopBoundaryTimer();
    S().activeSentence = -1;
    S().rangeEnd = 0;
    S().followActive = false;
    S().followPaused = false;
    clearFollowHighlight();
    notifyWindow();
    notifyTick();
  }

  function playQuestions(){
    const item = WB.paper.currentItem();
    if(item.questions.end > item.questions.start + 0.5){
      playRange(item.questions.start, item.questions.end, null, {kind:"questions"});
    }
  }

  function applyLoopCfg(i){
    if(i !== S().activeSentence) return;
    S().activeLoopCfg = WB.paper.loopCfgFor(i);
    S().repeatLeft = S().activeLoopCfg.on
      ? 0
      : Math.max(0, S().activeLoopCfg.times - 1);
  }

  function refreshWindow(i, autoPlayWhenAB){
    if(i !== S().activeSentence) return;
    const win = resolveWindow(i);
    if(!win) return;
    S().rangeStart = win.start;
    S().rangeEnd = win.end;
    S().ab = (win.mode === "ab") ? {a:win.start, b:win.end} : null;
    if(autoPlayWhenAB && win.mode === "ab"){
      document.querySelectorAll(".card").forEach(function(c){
        c.classList.toggle("playing", c.dataset.i === String(i));
      });
      audio.currentTime = win.start;
      const st = WB.paper.bumpLoopStat(i, "plays");
      notifyLoop(i, st);
      safePlay();
      startBoundaryTimer();
    }
    notifyWindow();
    notifyTick();
  }

  function setABPoint(i, which){
    if(i !== S().activeSentence) return {ok:false, message:"先选中这一句。"};
    const base = WB.paper.baseRangeByIndex(i);
    if(!base) return {ok:false, message:"找不到这一句。"};
    const t = U.clamp(audio.currentTime, base[0], Math.max(base[0], base[1] - 0.2));
    const res = WB.paper.setABPoint(i, which, t);
    if(!res.ok) return res;
    refreshWindow(i, which === "B");
    return res;
  }

  function clearAB(i){
    WB.paper.clearAB(i);
    if(i === S().activeSentence) refreshWindow(i, false);
  }

  function refreshActiveWindow(){
    const i = S().activeSentence;
    if(i >= 0) refreshWindow(i, false);
  }

  function init(){
    if(inited) return;
    inited = true;
    audio = WB.dom.audio;

    audio.addEventListener("loadedmetadata", function(){
      applyRate();
      updatePlayerUI();
      WB.status("音频就绪");
    });
    audio.addEventListener("durationchange", updatePlayerUI);
    audio.addEventListener("ended", updatePlayerUI);
    // 跟随由播放位置驱动，不靠边界定时器：暂停再继续也不会冻住。
    audio.addEventListener("timeupdate", function(){
      notifyTick();
    });
    audio.addEventListener("play", function(){
      applyRate();
      // 直接点底部原生播放器（没有走 playRange）时，也按整卷跟随当前句。
      if(S().activeSentence < 0 && !S().rangeEnd){
        S().followActive = true;
        S().followScope = "paper";
        S().followSectionSi = S().currentSi;
        S().followPaused = false;
      }
      // 暂停会停掉边界定时器；任何来源的继续播放都要把它接回来，
      // 否则单句循环 / 整段播完自动停都失效。
      if(S().rangeEnd > S().rangeStart) startBoundaryTimer();
      updateFollow();
      notifyTick();
    });
    audio.addEventListener("pause", function(){
      stopBoundaryTimer();
      notifyTick();
    });
    audio.addEventListener("ended", function(){
      stopBoundaryTimer();
      releaseRange();
      notifyWindow();
      notifyTick();
    });
    audio.addEventListener("error", function(){
      WB.status("音频加载失败：请确认试卷目录里有 audio.mp3。");
    });

    if(WB.dom.playPauseBtn){
      WB.dom.playPauseBtn.addEventListener("click", togglePlayPause);
    }
    if(WB.dom.playerSeek){
      WB.dom.playerSeek.addEventListener("pointerdown", function(){ seeking = true; });
      WB.dom.playerSeek.addEventListener("input", function(){
        seeking = true;
        seekToFraction(Number(WB.dom.playerSeek.value) / 1000);
      });
      WB.dom.playerSeek.addEventListener("change", function(){
        seekToFraction(Number(WB.dom.playerSeek.value) / 1000);
        seeking = false;
      });
      WB.dom.playerSeek.addEventListener("pointerup", function(){ seeking = false; });
      WB.dom.playerSeek.addEventListener("keydown", function(e){
        if(e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
        e.preventDefault();
        const step = e.shiftKey ? 5 : 1;
        seekBy(e.key === "ArrowRight" ? step : -step);
      });
    }
    window.addEventListener("pointerup", function(){ seeking = false; });
  }

  function loadRate(){
    S().playRate = WB.store.loadRate();
  }

  function applyRate(){
    if(audio) audio.playbackRate = S().playRate;
    if(WB.dom.playerRateBadge){
      WB.dom.playerRateBadge.textContent = (Math.round(S().playRate * 100) / 100) + "×";
    }
  }

  function setRate(r){
    S().playRate = Number(r) || 1;
    WB.store.saveRate(S().playRate);
    applyRate();
    notifyRate();
  }

  WB.audio = {
    init: init,
    url: url,
    safePlay: safePlay,
    resolveWindow: resolveWindow,
    playRange: playRange,
    playSentence: playSentence,
    toggleSentence: toggleSentence,
    seekFraction: seekFraction,
    focusSentence: focusSentence,
    moveSentence: moveSentence,
    replayActive: replayActive,
    jumpToStart: jumpToStart,
    playContent: playContent,
    playQuestions: playQuestions,
    playItem: playItem,
    playSection: playSection,
    stopPlayback: stopPlayback,
    applyLoopCfg: applyLoopCfg,
    setABPoint: setABPoint,
    clearAB: clearAB,
    refreshActiveWindow: refreshActiveWindow,
    startBoundaryTimer: startBoundaryTimer,
    stopBoundaryTimer: stopBoundaryTimer,
    invalidateTimeline: invalidateTimeline,
    setFollowPaused: setFollowPaused,
    seekBy: seekBy,
    seekToFraction: seekToFraction,
    togglePlayPause: togglePlayPause,
    updatePlayerUI: updatePlayerUI,
    updateFollow: updateFollow,
    loadRate: loadRate,
    applyRate: applyRate,
    setRate: setRate,
    isPaused: function(){ return !audio || audio.paused; },
    now: function(){ return audio ? audio.currentTime : 0; },
    hasSource: function(){ return !!(audio && audio.src); },
    onTick: null,
    onWindowChange: null,
    onRateChange: null,
    onLoopStat: null
  };
})(window.WB = window.WB || {});
