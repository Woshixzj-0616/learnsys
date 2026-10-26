// 精听标签：原工作台 iframe，query 原样转发（paper 深链不回归）。
export function mountListening(panel, query) {
  const params = new URLSearchParams(query || "");
  params.delete("tab");
  const extra = params.toString();
  const src = `/cet6/工作台/精听工作台.html?v=20261026c${extra ? `&${extra}` : ""}`;
  panel.innerHTML = `<iframe class="cet6-frame" src="${src}"
    title="六级精听工作台"></iframe>`;
  return () => { panel.innerHTML = ""; };
}
