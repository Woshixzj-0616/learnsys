// 翻译页的数据层：题库、历史、术语、单句的加载与缓存。
// 纯选择逻辑（挑一句、标记已练）也放这里，页面状态机只读结果。
import { api } from "../../api.js";

let promptsCache = null;
let historyCache = {};  // {whole: [], sentence: []}
let termsCache = null;
let sentenceCache = null;

export function invalidate() {
  promptsCache = null;
  historyCache = {};
  sentenceCache = null;
}

export async function loadPrompts() {
  if (!promptsCache) {
    const data = await api.get("/api/cet6/train/prompts?kind=translation");
    promptsCache = data.items || [];
  }
  return promptsCache;
}

export async function loadHistory(mode = "whole") {
  if (!historyCache[mode]) {
    const query = mode === "sentence" ? "&mode=sentence" : "";
    const data = await api.get(
      `/api/cet6/train/submissions?kind=translation&limit=50${query}`);
    historyCache[mode] = data.items || [];
  }
  return historyCache[mode];
}

export async function loadTerms(packId = "") {
  const key = packId || "*";
  if (!termsCache || termsCache.key !== key) {
    const data = await api.get(
      `/api/cet6/train/terms${packId ? `?pack_id=${encodeURIComponent(packId)}` : ""}`);
    termsCache = { key, items: data.items || [] };
  }
  return termsCache.items;
}

export async function loadSentences() {
  if (!sentenceCache) {
    const data = await api.get("/api/cet6/train/sentences?limit=500");
    sentenceCache = data;
  }
  return sentenceCache;
}

export function sentencesCache() {
  return sentenceCache;
}

// 已练计数与单句 attempted 标记的唯一写入口。
export function markSentenceAttempted(id) {
  if (!sentenceCache) return;
  const row = sentenceCache.items.find((item) => item.id === id);
  if (row) row.attempted = true;
  sentenceCache.attempted_count = (sentenceCache.attempted_count || 0) + 1;
}

// 优先没练过的；其次避开当前句；都没有就回到池子第一句。
export function pickSentence(skill, currentId) {
  const pool = (sentenceCache?.items || []).filter(
    (row) => !skill || row.skill === skill);
  return pool.find((row) => !row.attempted)
    || pool.find((row) => row.id !== currentId)
    || pool[0] || null;
}
