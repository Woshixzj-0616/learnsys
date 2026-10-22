// @requires: 00-core.js
// 网络层：HTTP 模式下唯一的后台出口。令牌从 /api/health 取，SSE 自己解析。
// file:// 模式 ready=false，需要后台的功能显示「请从学习工作台打开」。
(function(WB){
  "use strict";

  const HTTP = location.protocol === "http:" || location.protocol === "https:";
  let token = "";

  const api = {
    ready: false,
    HTTP: HTTP,
    init: init,
    get: get,
    post: post,
    patch: patch,
    del: del,
    download: download,
    stream: stream,
    errorText: errorText
  };

  async function init(){
    if(!HTTP){
      api.ready = false;
      return false;
    }
    try{
      const res = await fetch("/api/health", {cache:"no-store"});
      if(!res.ok) throw new Error("HTTP " + res.status);
      const data = await res.json();
      token = String((data && data.token) || "");
      api.ready = !!token;
    }catch(e){
      token = "";
      api.ready = false;
    }
    return api.ready;
  }

  function headers(){
    const h = {"Content-Type":"application/json"};
    if(token) h["X-Learnsys-Token"] = token;
    return h;
  }

  function ensure(){
    if(!api.ready) throw new Error("请从学习工作台打开（HTTP /cet6/）后再用这个功能。");
  }

  async function parseError(res){
    let detail = "";
    try{
      const text = await res.text();
      if(text){
        try{
          const data = JSON.parse(text);
          detail = String(data.detail || data.error || "");
        }catch(e){ detail = text.slice(0, 200); }
      }
    }catch(e){}
    const err = new Error(detail || ("HTTP " + res.status));
    err.status = res.status;
    return err;
  }

  async function get(path){
    ensure();
    const res = await fetch(path, {cache:"no-store", headers:headers()});
    if(!res.ok) throw await parseError(res);
    return res.json();
  }

  async function post(path, body){
    ensure();
    const res = await fetch(path, {
      method:"POST", headers:headers(),
      body:JSON.stringify(body || {})
    });
    if(!res.ok) throw await parseError(res);
    return res.json();
  }

  async function patch(path, body){
    ensure();
    const res = await fetch(path, {
      method:"PATCH", headers:headers(),
      body:JSON.stringify(body || {})
    });
    if(!res.ok) throw await parseError(res);
    return res.json();
  }

  async function del(path){
    ensure();
    const res = await fetch(path, {method:"DELETE", headers:headers()});
    if(!res.ok) throw await parseError(res);
    return res.json();
  }

  async function download(path, filename){
    ensure();
    const res = await fetch(path, {cache:"no-store", headers:headers()});
    if(!res.ok) throw await parseError(res);
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename || "下载.csv";
    a.click();
    URL.revokeObjectURL(a.href);
  }

  // 逐行解析 SSE：只认 data: 行，空行分隔事件。
  async function stream(path, body, onEvent, signal){
    ensure();
    const res = await fetch(path, {
      method:"POST", headers:headers(),
      body:JSON.stringify(body || {}), signal:signal
    });
    if(!res.ok) throw await parseError(res);
    if(!res.body || !res.body.getReader){
      throw new Error("当前浏览器不支持流式响应。");
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    const handle = function(chunk){
      chunk.split(/\r?\n/).forEach(function(line){
        if(line.indexOf("data:") !== 0) return;
        const raw = line.slice(5).trim();
        if(!raw) return;
        try{ onEvent(JSON.parse(raw)); }catch(e){}
      });
    };
    while(true){
      const step = await reader.read();
      if(step.done) break;
      buffer += decoder.decode(step.value, {stream:true});
      let at;
      while((at = buffer.indexOf("\n\n")) >= 0){
        handle(buffer.slice(0, at));
        buffer = buffer.slice(at + 2);
      }
    }
    if(buffer.trim()) handle(buffer);
  }

  function errorText(err){
    if(!err) return "未知错误";
    if(err.name === "AbortError") return "已停止";
    if(err.status === 403) return "后台令牌失效，请刷新页面。";
    if(err.status === 413) return "上下文太大，先少选一点内容。";
    if(err.status === 404) return "后台没有这条记录。";
    return err.message || "请求失败";
  }

  WB.api = api;
})(window.WB = window.WB || {});
