// 深链：今日提醒直达二稿或一句一译；参数读完就清，避免返回时重复触发。
export function readDeepLink(ctx) {
  return {
    id: Number(ctx?.query?.get("submission") || 0),
    rewrite: ctx?.query?.get("rewrite") === "1",
    skill: ctx?.query?.get("skill") || "",
  };
}

function clearHash(tab) {
  const url = new URL(location.href);
  url.hash = tab === "translation"
    ? "#/english?tab=writing&sub=translation"
    : "#/english?tab=writing";
  history.replaceState(null, "", url);
}

export async function openDeepLink({ ctx, tab, openSubmission, startRewrite, renderSentence }) {
  const link = readDeepLink(ctx);
  if (link.id) {
    await openSubmission(link.id);
    if (link.rewrite && startRewrite) await startRewrite(link.id);
    clearHash(tab);
    return true;
  }
  if (link.skill && renderSentence) {
    await renderSentence(link.skill);
    clearHash(tab);
    return true;
  }
  return false;
}
