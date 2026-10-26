// 限时 / 练习 / 二稿编辑器：自动保存、倒计时、粘贴与离开记录。
import { api } from "../../api.js";
import { escapeHtml } from "../../ui.js";
import { cjkCount, clock, countWords } from "./format.js";

function practiceNotes(prompt) {
  const angles = prompt?.angle_points || [];
  const arguments_ = prompt?.arguments || [];
  const patterns = prompt?.patterns || [];
  if (!angles.length && !arguments_.length && !patterns.length) return "";
  return `<details class="cet6-hints">
    <summary>思路提示（练习模式可见；限时模式不给）</summary>
    ${angles.length ? `<h4>审题要点</h4><ul>${angles.map((x) => `<li>${escapeHtml(x)}</li>`).join("")}</ul>` : ""}
    ${arguments_.length ? `<h4>可用分论点</h4><ul>${arguments_.map((x) => `<li>${escapeHtml(x)}</li>`).join("")}</ul>` : ""}
    ${patterns.length ? `<h4>可复用句式</h4><ul>${patterns.map((x) => `<li>${escapeHtml(x)}</li>`).join("")}</ul>` : ""}
  </details>`;
}

export function createEditor(options) {
  const {
    submission, prompt, initialText = "", priorities = [],
    kind = "writing", onSubmitted, onBack, onToast,
  } = options;
  const translation = kind === "translation";
  const timed = submission.mode === "timed";
  const totalSeconds = Math.max(60, Number(prompt?.minutes || 30) * 60);
  const startedAt = Date.now() - Number(submission.duration_s || 0) * 1000;
  let pastedChars = Number(submission.flags?.pasted_chars || 0);
  let leftSeconds = Number(submission.flags?.left_seconds || 0);
  let hiddenAt = 0;
  let dirty = false;
  let submitting = false;
  let stopped = false;
  let autosaveTimer = null;
  let clockTimer = null;
  let armed = false;

  const el = document.createElement("div");
  el.className = "cet6-editor";
  const kicker = translation
    ? (timed ? "翻译 · 限时模式 · 提交前不看参考译文" : "翻译 · 练习模式")
    : (timed ? "限时模式 · 提交前不看范文"
      : (submission.mode === "rewrite" ? "二稿 · 只改最影响分数的点" : "练习模式"));
  const meta = translation
    ? `${prompt?.theme || ""} · ${prompt?.minutes || 30} 分钟 · 原文 ${cjkCount(prompt?.source_zh)} 字`
    : `${prompt?.type || ""} · 目标 ${(prompt?.target_words || [150, 200]).join("–")} 词`;
  const promptPanel = translation
    ? `<p class="cet6-source-zh">${escapeHtml(prompt?.source_zh || "")}</p>
       <p class="hint">先自己译，提交后才给参考译文；卡住时用「一句一译」的两级提示。</p>`
    : `<p class="cet6-prompt-en">${escapeHtml(prompt?.prompt_en || "")}</p>
       ${prompt?.prompt_zh ? `<p class="hint">${escapeHtml(prompt.prompt_zh)}</p>` : ""}
       ${submission.mode === "rewrite" && priorities.length
         ? `<div class="cet6-rewrite-list"><h4>二稿只改这三处</h4><ol>${priorities.map((x) => `<li>${escapeHtml(x)}</li>`).join("")}</ol></div>`
         : ""}
       ${submission.mode === "practice" ? practiceNotes(prompt) : ""}`;
  el.innerHTML = `<header class="cet6-editor-head">
      <div>
        <span class="cet6-kicker">${kicker}</span>
        <h2>${escapeHtml(prompt?.title || (translation ? "翻译" : "写作"))}</h2>
        <p class="hint">${escapeHtml(meta)}</p>
      </div>
      <div class="cet6-timer${timed ? "" : " off"}" id="cet6-timer">${timed ? clock(totalSeconds) : "不限时"}</div>
    </header>
    <div class="cet6-editor-body">
      <aside class="cet6-prompt">${promptPanel}</aside>
      <section class="cet6-write">
        <textarea id="cet6-text" spellcheck="false" placeholder="${translation ? "在这里写英文译文…" : "在这里写英文作文（150–200 词）…"}"></textarea>
        <div class="cet6-write-foot">
          <div class="cet6-write-meta">
            <span id="cet6-words">0 词</span>
            <span id="cet6-save" class="hint">未保存</span>
            <span id="cet6-paste" class="hint"></span>
          </div>
          <div class="cet6-actions">
            <button class="btn btn-small" type="button" id="cet6-leave">先离开</button>
            <button class="btn btn-primary" type="button" id="cet6-submit">提交批改</button>
          </div>
        </div>
      </section>
    </div>`;

  const textarea = el.querySelector("#cet6-text");
  const wordsNode = el.querySelector("#cet6-words");
  const saveNode = el.querySelector("#cet6-save");
  const pasteNode = el.querySelector("#cet6-paste");
  const timerNode = el.querySelector("#cet6-timer");
  const submitButton = el.querySelector("#cet6-submit");
  const leaveButton = el.querySelector("#cet6-leave");
  const target = (prompt?.target_words || [150, 200]);
  textarea.value = initialText || submission.text || "";

  function renderCounts() {
    const words = countWords(textarea.value);
    wordsNode.textContent = `${words} 词`;
    if (translation) {
      wordsNode.classList.remove("warn");
      wordsNode.classList.remove("bad");
      return;
    }
    wordsNode.classList.toggle("warn", words < Number(target[0] || 150));
    wordsNode.classList.toggle("bad", words < Math.floor(Number(target[0] || 150) * 0.9));
  }

  function elapsed() {
    return Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
  }

  function tick() {
    if (stopped || !timed) return;
    const left = totalSeconds - elapsed();
    timerNode.textContent = clock(left);
    timerNode.classList.toggle("bad", left <= 300);
    if (left <= 0 && armed && !submitting) {
      onToast?.("时间到，正在自动提交");
      doSubmit();
    }
  }

  function markDirty() {
    dirty = true;
    saveNode.textContent = "待保存…";
    renderCounts();
  }

  async function save() {
    const payload = {
      text: textarea.value,
      duration_s: elapsed(),
      pasted_chars: pastedChars,
      left_seconds: leftSeconds,
    };
    try {
      await api.patch(`/api/cet6/train/submissions/${submission.id}`, payload);
      dirty = false;
      saveNode.textContent = "已保存";
      saveNode.classList.remove("bad");
      return true;
    } catch (error) {
      saveNode.textContent = "保存失败";
      saveNode.classList.add("bad");
      console.warn("自动保存失败", error);
      return false;
    }
  }

  async function doSubmit() {
    if (submitting || stopped) return;
    submitting = true;
    clearInterval(autosaveTimer);
    submitButton.disabled = true;
    submitButton.textContent = "提交中…";
    const ok = await save();
    if (!ok) {
      submitting = false;
      submitButton.disabled = false;
      submitButton.textContent = "提交批改";
      onToast?.("保存失败，先别提交；检查后台连接");
      return;
    }
    try {
      const data = await api.post(
        `/api/cet6/train/submissions/${submission.id}/submit`,
        { pasted_chars: pastedChars, left_seconds: leftSeconds });
      stopped = true;
      clearInterval(clockTimer);
      onSubmitted?.(data);
    } catch (error) {
      submitting = false;
      submitButton.disabled = false;
      submitButton.textContent = "提交批改";
      onToast?.(error.message || "提交失败");
    }
  }

  textarea.addEventListener("input", markDirty);
  textarea.addEventListener("paste", (event) => {
    const added = (event.clipboardData?.getData("text") || "").length;
    if (added) {
      pastedChars += added;
      pasteNode.textContent = `已记录粘贴 ${pastedChars} 字`;
      pasteNode.classList.add("warn");
    }
  });
  submitButton.addEventListener("click", doSubmit);
  leaveButton.addEventListener("click", async () => {
    await save();
    stopped = true;
    clearInterval(clockTimer);
    onBack?.();
  });

  const onVisibility = () => {
    if (document.hidden) {
      hiddenAt = Date.now();
    } else if (hiddenAt) {
      leftSeconds += Math.max(0, Math.round((Date.now() - hiddenAt) / 1000));
      hiddenAt = 0;
      dirty = true;          // 离开时长要落库，不能等下一次打字才保存
      save();
    }
  };
  const onBeforeUnload = (event) => {
    if (!dirty) return;
    event.preventDefault();
    event.returnValue = "还有没保存的内容";
  };
  document.addEventListener("visibilitychange", onVisibility);
  window.addEventListener("beforeunload", onBeforeUnload);

  renderCounts();
  if (submission.flags?.pasted_chars) {
    pasteNode.textContent = `已记录粘贴 ${pastedChars} 字`;
  }
  if (timed) {
    tick();
    clockTimer = setInterval(tick, 1000);
    setTimeout(() => { armed = true; }, 1200);   // 打开页面那一刻不误触自动提交
  }
  autosaveTimer = setInterval(() => { if (dirty && !submitting) save(); }, 5000);

  function stop() {
    stopped = true;
    clearInterval(clockTimer);
    clearInterval(autosaveTimer);
    document.removeEventListener("visibilitychange", onVisibility);
    window.removeEventListener("beforeunload", onBeforeUnload);
    if (dirty) save().catch(() => {});
  }

  return { el, stop, save };
}
