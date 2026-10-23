// 测验文本解析（纯函数）：题块、知识点、批改对错、上报 payload。
// 只做字符串处理，不碰 DOM / 网络，node --test 可直接加载。

const QUESTION_RE = /【第\s*(\d+)\s*题】([\s\S]*?)(?=【第\s*\d+\s*题】|【批改】|$)/g;
const KNOWLEDGE_RE = /【知识点】\s*([^\n]*)/;

function clean(text) {
  return String(text || "").replace(/\*\*/g, "").trim();
}

export function parseKnowledge(text) {
  const match = String(text || "").match(KNOWLEDGE_RE);
  if (!match) return {names: [], found: false};
  const names = match[1]
    .split(/[、,，;；]+/)
    .map((item) => clean(item))
    .filter(Boolean);
  return {names, found: names.length > 0};
}

export function parseQuestionStem(block) {
  return String(block || "")
    .replace(/【知识点】[^\n]*/g, "")
    .trim();
}

export function parseQuestionBlocks(text) {
  const out = [];
  for (const match of String(text || "").matchAll(QUESTION_RE)) {
    const block = match[2] || "";
    out.push({
      no: Number(match[1]) || 0,
      stem: parseQuestionStem(block),
      points: parseKnowledge(block).names,
    });
  }
  return out;
}

export function parseLastQuestion(text) {
  const blocks = parseQuestionBlocks(text);
  return blocks.length ? blocks[blocks.length - 1] : null;
}

const POSITIVE = /^(?:你|回答|答案)?\s*(完全正确|正确|对了|答对了|答对|回答正确)(?=$|[\s，,。.！!？?：:；;）)]|\*\*)/;
const NEGATIVE = /^(?:你|回答|答案)?\s*(不完全正确|部分正确|基本正确|不太正确|不正确|错误|错了|答错了|答错|不对)/;

function judge(line) {
  const text = clean(line).replace(/^[：:，,。.\s]+/, "");
  if (!text) return null;
  // 否定词必须先判，否则「不正确」「部分正确」会被「正确」吃掉。
  if (NEGATIVE.test(text)) return false;
  if (POSITIVE.test(text)) return true;
  return null;
}

function conservativeFallback(raw) {
  const first = String(raw || "").split(/\r?\n/).map((line) => clean(line))
    .find(Boolean) || "";
  const correct = judge(first);
  return {found: false, correct, body: String(raw || "").trim()};
}

export function parseGrading(text) {
  const raw = String(text || "");
  const at = raw.lastIndexOf("【批改】");
  if (at < 0) return conservativeFallback(raw);
  const tail = raw.slice(at + "【批改】".length);
  const segment = tail.split(/【第\s*\d+\s*题】|【知识点】/)[0].trim();
  const lines = segment.split(/\r?\n/);
  const firstIndex = lines.findIndex((line) => clean(line));
  const firstLine = firstIndex >= 0 ? clean(lines[firstIndex]) : "";
  const correct = judge(firstLine);
  // 反馈里不重复「正确/错误」这行结论，只留原因。
  const body = correct !== null && firstIndex >= 0
    ? lines.slice(firstIndex + 1).join("\n").trim()
    : segment;
  return {found: true, correct, body};
}

export function buildAttemptPayload({conversationId = 0, materialId = 0,
                                     questionNo = 0, question = "", answer = "",
                                     grading = null, points = []} = {}) {
  const q = String(question || "").trim();
  const a = String(answer || "").trim();
  if (!q || !a) return null;
  const correct = grading && typeof grading.correct === "boolean"
    ? grading.correct : null;
  return {
    conversation_id: Number(conversationId) || 0,
    material_id: Number(materialId) || 0,
    question_no: Number(questionNo) || 0,
    question: q,
    my_answer: a,
    correct,
    feedback: grading && grading.body ? String(grading.body).slice(0, 2000) : "",
    points: Array.isArray(points) ? points.slice(0, 3) : [],
  };
}
