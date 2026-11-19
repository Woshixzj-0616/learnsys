// @requires: 00-core.js, 10-storage.js, 20-paper.js, 40-render.js, 55-api.js
// 本题组做 A-D 选择题：本地判分，HTTP 模式下把错题号写进六级做题统计。
(function(WB){
  "use strict";

  const U = WB.util;

  function itemId(){
    return WB.paper.currentItemId();
  }

  function quizData(){
    return WB.paper.quizForItem();
  }

  function state(){
    WB.state.quiz = WB.state.quiz || {};
    WB.state.quiz[itemId()] = WB.state.quiz[itemId()] || {answers:{}};
    return WB.state.quiz[itemId()];
  }

  function paperId(){
    if(WB.cet6Sync && WB.cet6Sync.paperId) return WB.cet6Sync.paperId();
    return WB.session.paperDir ||
      (WB.session.paper && WB.session.paper.title) || "";
  }

  function grade(questions, answers){
    const wrong = [];
    const keys = Object.keys(questions || {});
    keys.forEach(function(key){
      if(!answers || answers[key] !== questions[key].answer) wrong.push(Number(key));
    });
    wrong.sort(function(a, b){ return a - b; });
    return {wrong:wrong, correct:keys.length - wrong.length, total:keys.length};
  }

  function choose(qnum, label){
    const st = state();
    st.answers = st.answers || {};
    st.answers[String(qnum)] = String(label || "").toUpperCase();
    st.startedAt = st.startedAt || Date.now();
    WB.store.saveState();
    if(WB.render && WB.render.questions) WB.render.questions();
  }

  async function submit(){
    const quiz = quizData();
    if(!quiz) return;
    const st = state();
    const result = grade(quiz.questions, st.answers);
    st.submitted = true;
    st.correct = result.correct;
    st.total = result.total;
    st.wrong = result.wrong;
    st.at = Date.now();
    st.duration = Math.max(0, Math.round((Date.now() - (st.startedAt || Date.now())) / 1000));
    WB.store.saveState();
    if(WB.render && WB.render.questions) WB.render.questions();
    WB.status("本题组：" + result.correct + " / " + result.total + " 题。");

    if(!WB.api || !WB.api.ready){
      st.synced = false;
      WB.store.saveState();
      return;
    }
    const sec = WB.paper.currentSection();
    const item = WB.paper.currentItem();
    try{
      if(WB.cet6Sync && WB.cet6Sync.syncPaper) await WB.cet6Sync.syncPaper();
      await WB.api.post("/api/cet6/exam/attempt", {
        paper_id: paperId(),
        section: sec.name,
        item: item.title,
        wrong: result.wrong,
        duration_s: st.duration,
        numbers: Object.keys(quiz.questions).map(Number)
      });
      st.synced = true;
      WB.status("做题成绩已写入统计：" + result.correct + " / " + result.total + " 题。");
    }catch(e){
      st.synced = false;
      WB.status("本地已判分，但未同步到统计：" + (e.message || "请求失败"));
    }
    WB.store.saveState();
  }

  function redo(){
    if(WB.state.quiz) delete WB.state.quiz[itemId()];
    WB.store.saveState();
    if(WB.render && WB.render.questions) WB.render.questions();
    WB.status("已清空本题组答案，可以重做。");
  }

  WB.quiz = {choose: choose, submit: submit, redo: redo, grade: grade,
             itemId: itemId, state: state};
})(WB);
