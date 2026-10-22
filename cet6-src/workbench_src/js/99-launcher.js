// @requires: 00-core.js, 10-storage.js, 90-boot.js
// 启动器层：最后执行。加载试卷索引与 data.js，构建试卷选择器，然后调用 WB.boot。
(function(WB){
  "use strict";

  const U = WB.util;
  const INDEX = "../试卷/试卷索引.js";

  function loadScript(src){
    return new Promise(function(resolve, reject){
      const s = document.createElement("script");
      s.src = src;
      s.onload = resolve;
      s.onerror = function(){ reject(new Error(src)); };
      document.head.appendChild(s);
    });
  }

  function withCacheBust(src){
    return src + (src.indexOf("?") >= 0 ? "&" : "?") + "t=" + Date.now();
  }

  function renderRecent(){
    const panel = document.getElementById("recentPanel");
    if(!panel) return;
    const arr = WB.store.readHistory();
    panel.innerHTML = "";
    if(!arr.length){
      panel.innerHTML = '<p class="recent-empty">还没有听过的试卷。打开一份试卷后会自动记录。</p>';
      return;
    }
    arr.forEach(function(h){
      const b = document.createElement("button");
      b.type = "button";
      b.className = "recent-item";
      const prog = h.total ? " · " + h.done + "/" + h.total + " 句" : "";
      b.innerHTML =
        '<span class="t"><b>' + U.escapeHtml(h.title) + "</b>" +
        (h.posLabel ? '<br><span class="m">' + U.escapeHtml(h.posLabel) + "</span>" : "") +
        '</span><span class="m">' + U.ago(h.at) + prog + "</span>";
      b.addEventListener("click", function(){
        const url = new URL(location.href);
        url.search = "?paper=" + encodeURIComponent(h.dir);
        location.href = url.href;
      });
      panel.appendChild(b);
    });
  }

  function exportAllData(){
    const data = WB.store.collectAllData();
    const blob = new Blob([JSON.stringify(data, null, 2)],
      {type:"application/json;charset=utf-8"});
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "精听学习数据-" + new Date().toISOString().slice(0, 10) + ".json";
    a.click();
    URL.revokeObjectURL(a.href);
  }

  function importAllData(file){
    const reader = new FileReader();
    reader.onload = function(){
      try{
        const data = JSON.parse(String(reader.result));
        const n = (data && data.store) ? Object.keys(data.store).length : 0;
        if(n && !confirm("将导入 " + n + " 项学习数据，同名数据会被覆盖。继续？")) return;
        const count = WB.store.importData(data);
        alert("导入完成，共 " + count + " 项，页面将刷新。");
        location.reload();
      }catch(e){
        alert("导入失败：" + e.message);
      }
    };
    reader.readAsText(file, "utf-8");
  }

  function fail(message){
    window.showLaunchError(message);
    const select = document.getElementById("paperSelect");
    if(select) select.disabled = true;
  }

  async function main(){
    try{
      await loadScript(withCacheBust(INDEX));
    }catch(e){
      fail("找不到 试卷\\试卷索引.js。\n请先运行一次分割工具，或执行：\n" +
        "D:\\cet6_tool\\.venv\\Scripts\\python.exe D:\\cet6_tool\\split_listening.py --refresh-index --out \"D:\\Desktop\\六级精听\\试卷\"");
      return;
    }

    const papers = Array.isArray(window.PAPERS) ? window.PAPERS : [];
    const select = document.getElementById("paperSelect");
    const indexTime = document.getElementById("paperIndexTime");
    if(indexTime && window.PAPERS_UPDATED_AT){
      const raw = String(window.PAPERS_UPDATED_AT);
      const m = /(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(raw);
      indexTime.textContent = m ? "索引 " + m[4] + ":" + m[5] : "";
      indexTime.title = "试卷索引更新时间：" + raw;
    }
    if(!papers.length){
      fail("试卷索引是空的。请先用“拖入音频分割.bat”生成一份试卷。");
      return;
    }

    const wanted = new URLSearchParams(location.search).get("paper") || WB.store.getLast();
    const current = papers.some(function(p){ return p.dir === wanted; })
      ? wanted
      : papers[0].dir;

    function groupOf(p){
      const m = /(\d{4})\s*年\s*(\d{1,2})\s*月/.exec(p.title || "");
      if(m) return m[1] + "年" + String(m[2]).padStart(2, "0") + "月";
      const c = /(\d{4})-(\d{2})/.exec(p.created_at || "");
      return c ? c[1] + "年" + c[2] + "月" : "其他";
    }

    function mmss(sec){
      const s = Math.round(Number(sec) || 0);
      return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
    }

    function buildOptions(filter){
      const q = String(filter || "").trim().toLowerCase();
      const map = new Map();
      papers.forEach(function(p){
        const hay = (p.title + " " + p.dir + " " + (p.created_at || "")).toLowerCase();
        if(q && hay.indexOf(q) < 0) return;
        const g = groupOf(p);
        if(!map.has(g)) map.set(g, []);
        map.get(g).push(p);
      });
      select.innerHTML = "";
      const groups = Array.from(map.keys()).sort().reverse();
      if(!groups.length){
        const opt = new Option("没有匹配的试卷", "");
        opt.disabled = true;
        select.appendChild(opt);
        return;
      }
      groups.forEach(function(g){
        const og = document.createElement("optgroup");
        og.label = g;
        map.get(g).sort(function(a, b){ return a.title.localeCompare(b.title, "zh"); });
        map.get(g).forEach(function(p){
          const dur = p.duration ? " · " + mmss(p.duration) : "";
          const total = (p.stats && p.stats.sentences) || 0;
          const done = WB.store.paperDoneCount(p);
          const prog = total ? " · " + done + "/" + total + " 句" : "";
          const mark = (total && done >= total) ? " ✓" : "";
          const option = new Option(p.title + dur + prog + mark, p.dir);
          option.selected = (p.dir === current);
          og.appendChild(option);
        });
        select.appendChild(og);
      });
    }

    buildOptions("");
    select.disabled = false;
    select.addEventListener("change", function(){
      if(select.value === current) return;
      WB.store.setLast(select.value);
      const url = new URL(location.href);
      url.search = "?paper=" + encodeURIComponent(select.value);
      location.href = url.href;
    });

    const search = document.getElementById("paperSearch");
    search.addEventListener("input", function(){ buildOptions(search.value); });

    const recentBtn = document.getElementById("recentBtn");
    const recentPanel = document.getElementById("recentPanel");
    recentBtn.addEventListener("click", function(){
      const show = recentPanel.classList.contains("hidden");
      if(show) renderRecent();
      recentPanel.classList.toggle("hidden", !show);
      recentBtn.classList.toggle("on", show);
      recentBtn.setAttribute("aria-expanded", show ? "true" : "false");
    });
    renderRecent();

    document.getElementById("exportAllBtn").addEventListener("click", exportAllData);
    const importFile = document.getElementById("importFile");
    document.getElementById("importAllBtn").addEventListener("click", function(){
      importFile.click();
    });
    importFile.addEventListener("change", function(){
      if(importFile.files && importFile.files[0]) importAllData(importFile.files[0]);
      importFile.value = "";
    });

    const base = "../试卷/" + encodeURIComponent(current) + "/";
    try{
      await loadScript(withCacheBust(base + "data.js"));
    }catch(e){
      fail("找不到试卷「" + current + "」的 data.js，索引可能已过期。\n请重新运行 --refresh-index 刷新索引。");
      return;
    }
    if(!window.PAPER){
      fail("data.js 已加载，但没有 window.PAPER。");
      return;
    }

    WB.store.setLast(current);
    WB.boot({paper: window.PAPER, paperDir: current, audioBase: base});
  }

  main();
})(window.WB = window.WB || {});
