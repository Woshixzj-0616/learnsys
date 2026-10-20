// Markdown / 代码 / 公式渲染。marked 生成 → DOMPurify 清洗 → 再补交互。
// 安全顺序不能反：先清洗再挂按钮，别把模型输出当 HTML 信任。

marked.setOptions({ gfm: true, breaks: false, headerIds: false, mangle: false });

const SAFE = {
  ADD_ATTR: ["target", "rel"],
  FORBID_TAGS: ["script", "style", "iframe", "object", "embed"],
};

export function render(text) {
  return DOMPurify.sanitize(marked.parse(String(text || "")), SAFE);
}

/** 把一段 Markdown 放进容器，并补代码高亮、复制按钮、公式、「想一想」卡片。 */
export function renderInto(el, text) {
  el.innerHTML = render(text);
  enhance(el);
}

export function enhance(el) {
  // 外链新窗口，不把工作台带走
  el.querySelectorAll("a[href]").forEach((a) => {
    if (/^https?:/i.test(a.getAttribute("href") || "")) {
      a.target = "_blank";
      a.rel = "noreferrer noopener";
    }
  });

  // 表格窄窗口横向滚动
  el.querySelectorAll("table").forEach((table) => {
    if (table.parentElement?.classList.contains("table-wrap")) return;
    const wrap = document.createElement("div");
    wrap.className = "table-wrap";
    table.replaceWith(wrap);
    wrap.appendChild(table);
  });

  // 代码高亮 + 复制
  el.querySelectorAll("pre > code").forEach((code) => {
    try {
      window.hljs?.highlightElement(code);
    } catch {
      // 语言不认识就保持原样
    }
    const pre = code.parentElement;
    if (!pre || pre.parentElement?.classList.contains("code-block")) return;
    const wrap = document.createElement("div");
    wrap.className = "code-block";
    pre.replaceWith(wrap);
    wrap.appendChild(pre);

    const lang = [...code.classList]
      .find((name) => name.startsWith("language-"))
      ?.replace("language-", "");
    if (lang && lang !== "plaintext") {
      const label = document.createElement("span");
      label.className = "code-lang";
      label.textContent = lang;
      wrap.appendChild(label);
    }
    const copy = document.createElement("button");
    copy.type = "button";
    copy.className = "copy-code";
    copy.textContent = "复制";
    copy.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(code.textContent || "");
        copy.textContent = "已复制";
      } catch {
        copy.textContent = "复制失败";
      }
      setTimeout(() => { copy.textContent = "复制"; }, 1400);
    });
    wrap.appendChild(copy);
  });

  // 「想一想」→ 单独一张卡（提示词固定用标题收尾）
  const headings = [...el.querySelectorAll("h1, h2, h3, h4")];
  for (const heading of headings) {
    if (!heading.textContent.includes("想一想")) continue;
    if (heading.closest(".think-card")) continue;
    const level = Number(heading.tagName.slice(1));
    const card = document.createElement("div");
    card.className = "think-card";
    heading.replaceWith(card);
    card.appendChild(heading);
    let node = card.nextSibling;
    while (node) {
      const isHeading = node.nodeType === 1 && /^H[1-4]$/.test(node.tagName);
      if (isHeading && Number(node.tagName.slice(1)) <= level) break;
      const next = node.nextSibling;
      card.appendChild(node);
      node = next;
    }
    addThinkAnswer(card);
  }

  // 有的模型不写标题，只写一段「**想一想**」；同样收成卡片
  for (const paragraph of [...el.querySelectorAll("p")]) {
    const text = paragraph.textContent.trim();
    if (!text.startsWith("想一想") || text.length > 14) continue;
    if (paragraph.closest(".think-card")) continue;
    const card = document.createElement("div");
    card.className = "think-card";
    paragraph.replaceWith(card);
    card.appendChild(paragraph);
    let node = card.nextSibling;
    while (node) {
      if (node.nodeType === 1 && /^H[1-6]$/.test(node.tagName)) break;
      const next = node.nextSibling;
      card.appendChild(node);
      node = next;
    }
    addThinkAnswer(card);
  }

  // 公式：$...$ / $$...$$ / \(...\) / \[...\]
  if (window.renderMathInElement) {
    try {
      window.renderMathInElement(el, {
        delimiters: [
          { left: "$$", right: "$$", display: true },
          { left: "\\[", right: "\\]", display: true },
          { left: "$", right: "$", display: false },
          { left: "\\(", right: "\\)", display: false },
        ],
        throwOnError: false,
        ignoredTags: ["script", "noscript", "style", "textarea", "pre", "code", "option"],
      });
    } catch (error) {
      console.warn("公式渲染失败", error);
    }
  }
}

function addThinkAnswer(card) {
  if (card.querySelector(".think-answer")) return;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "think-answer";
  button.textContent = "我答一下";
  button.addEventListener("click", () => {
    window.dispatchEvent(new CustomEvent("learnsys:answer-think"));
  });
  card.appendChild(button);
}

/** 纯文本预览：去掉 Markdown 符号，给时间线和会话列表用。 */
export function plain(text, limit = 160) {
  const raw = String(text || "")
    .replace(/```[\s\S]*?```/g, "［代码］")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/[*_~>#-]+/g, "")
    .replace(/\s+/g, " ")
    .trim();
  return raw.length > limit ? raw.slice(0, limit) + "…" : raw;
}
