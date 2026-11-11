// 英语复习的纯逻辑：本轮进度、日期、卡片提示方向、答案比较。
// 不碰 DOM，方便 node --test 直接测；页面状态仍由 english-review.js 持有。

export const ROUND_SIZE = 10;
const STORE_VERSION = 1;
const CJK = /[一-鿿]/;

// 后端 dt.date.today() 是本地日期；这里也必须用本地日期，不能用 toISOString()。
export function localDay(now = new Date()) {
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function roundStorageKey(kind, day) {
  return `learnsys.er.round.${kind}.${day}`;
}

export function loadRound(storage, kind, day) {
  try {
    const raw = storage?.getItem(roundStorageKey(kind, day));
    if (!raw) return null;
    const data = JSON.parse(raw);
    if (!data || data.v !== STORE_VERSION || data.day !== day) return null;
    return {
      done: Math.max(0, Math.min(ROUND_SIZE, Number(data.done) || 0)),
      current: data.current && typeof data.current === "object"
        ? data.current : null,
    };
  } catch {
    return null;
  }
}

export function saveRound(storage, kind, day, patch = {}) {
  try {
    const prev = loadRound(storage, kind, day) || { done: 0, current: null };
    const next = {
      v: STORE_VERSION,
      day,
      done: Math.max(0, Math.min(ROUND_SIZE,
        Number(patch.done ?? prev.done) || 0)),
      current: "current" in patch ? patch.current : prev.current,
    };
    storage?.setItem(roundStorageKey(kind, day), JSON.stringify(next));
    return next;
  } catch {
    return null;
  }
}

export function clearRound(storage, kind, day) {
  try {
    storage?.removeItem(roundStorageKey(kind, day));
  } catch {
    // 存不进不影响复习
  }
}

export function cardKey(card) {
  if (!card) return "";
  return `${card.item_type || ""}:${card.item_id ?? ""}`;
}

// 生词释义常是「住房｜拼写错误…」；正面只取词义那一段，错因留到背面。
export function chineseGloss(meaning) {
  return String(meaning || "").split(/[｜|]/)[0].trim();
}

export function wordPrompt(card) {
  const isAccum = card?.accum_kind === "translation";
  const wordText = String(card?.word || "").trim();
  const meaningText = String(card?.meaning || "").trim();
  const gloss = chineseGloss(meaningText);
  const hint = String(card?.context || "").trim();

  // 每日积累的翻译短语：中文短语 -> 英文表达。
  if (isAccum) {
    return { direction: "zh2en", prompt: wordText, answer: meaningText, hint };
  }
  // 生词：释义里有中文 -> 看中文打英文；中文词头 + 英文释义也走同一方向。
  if (CJK.test(gloss) && !CJK.test(wordText)) {
    return { direction: "zh2en", prompt: gloss, answer: wordText, hint };
  }
  if (CJK.test(wordText) && !CJK.test(meaningText)) {
    return { direction: "zh2en", prompt: wordText, answer: meaningText, hint };
  }
  // 没有中文可做提示时回退旧方向：英文正面 -> 写中文释义。
  return { direction: "en2zh", prompt: wordText, answer: meaningText, hint: "" };
}

export function normalizeAnswer(text) {
  return String(text || "")
    .toLowerCase()
    .replace(/[（(][^）)]*[）)]/g, " ")     // 括号里的缩写不算错
    .replace(/[^\p{L}\p{N}\s-]/gu, " ")
    .replace(/-/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

// 软比较：只给「一致 / 基本一致 / 不同」提示，不替用户评分。
// 多个可接受答案用中文分号、顿号、斜杠分隔。
export function matchesAnswer(answer, typed) {
  const want = normalizeAnswer(typed);
  if (!want) return "";
  const parts = String(answer || "").split(/[；;、/|]/)
    .map(normalizeAnswer).filter(Boolean);
  if (!parts.length) return "";
  if (parts.some((part) => part === want)) return "same";
  if (parts.some((part) => {
    if (Math.min(part.length, want.length) < 2) return false;
    return part.includes(want) || want.includes(part);
  })) return "close";
  return "different";
}

// 写作句型卡的三关：0 = 缺内容不进入三关；1 例句回译；2 句型默写；3 换主题造句。
// 只看 reps 会把「连评忘了」的卡也推进下一关，所以同时要求 FSRS 稳定度达标。
export function writingStage(card) {
  const pattern = String(card?.pattern || card?.answer || "").trim();
  if (!pattern) return 0;
  const example = String(card?.example || "").trim();
  const exampleZh = String(card?.example_zh || "").trim();
  if (!example || !exampleZh) return 2;
  const state = String(card?.state || "");
  const reps = Number(card?.reps || 0);
  const lapses = Number(card?.lapses || 0);
  const progress = Math.max(0, reps - lapses);   // 评 1 也算一次 reps，不能拿来升级
  const stability = Number(card?.stability || 0);
  if (state === "review" && progress >= 3 && stability >= 5) return 3;
  if (state === "review" && progress >= 2 && stability >= 2.5) return 2;
  return 1;
}

// 只留固定词，把 ... / … / 下划线统一成可填的空。
export function patternHint(pattern) {
  return String(pattern || "").replace(/(?:\.{2,}|…+|__+)/g, "____");
}

export function patternSlots(pattern) {
  const matches = String(pattern || "").match(/\.{2,}|…+|__+/g);
  return matches ? matches.length : 0;
}

const WRITING_STOPWORDS = new Set(
  "a an the of to in on at for and or but as by with from".split(" "));

// 参考句/句型里的关键词：保留 be 动词、代词和 that/which，它们是句型骨架。
export function contentWords(text) {
  const plain = String(text || "").replace(/(?:\.{2,}|…+|__+)/g, " ");
  return [...new Set(normalizeAnswer(plain).split(" ").filter(Boolean)
    .filter((word) => !WRITING_STOPWORDS.has(word)))];
}

// 软对照：只数参考里的关键词写到了几个，不判对错。
export function keywordCoverage(reference, typed) {
  const words = contentWords(reference);
  const said = normalizeAnswer(typed);
  if (!said || !words.length) return { hit: 0, total: 0, missing: [] };
  const typedWords = new Set(said.split(" ").filter(Boolean));
  const missing = words.filter((word) => !typedWords.has(word));
  return { hit: words.length - missing.length, total: words.length, missing };
}

export function shouldDecrementQuota(card, quotaTypes) {
  if (!card || !Array.isArray(quotaTypes)) return false;
  return card.state === "new" && quotaTypes.includes(card.item_type);
}
