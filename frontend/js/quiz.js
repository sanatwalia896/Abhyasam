// Saved sets, navigation, bookmarks and review inspired by Hyperverge_quiz_preparation.
const API = window.ABHYASAM_API_BASE;
const $ = id => document.getElementById(id);
let activeSet, questions = [], index = 0, answers = {}, bookmarks = new Set(), started = 0, timer, busy = false;

async function request(path, options = {}) {
  const response = await fetch(API + path, options);
  const raw = await response.text();
  let data;
  try { data = JSON.parse(raw); } catch { throw new Error("Server returned a non-JSON response (" + response.status + ")."); }
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail));
  return data;
}
function status(message, error = false) {
  $("status").textContent = message;
  $("status").className = error ? "error" : "";
}
function screen(name) {
  ["library", "quiz", "results"].forEach(key => $(key + "-screen").hidden = key !== name);
}
function button(text, action, className = "") {
  const item = document.createElement("button");
  item.textContent = text; item.className = className;
  item.onclick = () => Promise.resolve().then(action).catch(error => status(error.message, true));
  return item;
}
async function library() {
  const data = await request("/api/mcq/sets");
  $("sets").replaceChildren();
  $("library-count").textContent = data.question_sets.length + " / 10 sets";
  if (!data.question_sets.length) $("sets").textContent = "No saved quizzes yet. Generate your first set above.";
  data.question_sets.forEach(set => {
    const card = document.createElement("article"); card.className = "set-card";
    const title = document.createElement("h3"); title.textContent = set.title;
    const description = document.createElement("p");
    description.textContent = set.question_count + " questions · " + (set.page_title || "Mixed topics");
    const actions = document.createElement("div"); actions.className = "actions";
    actions.append(button("Start quiz", () => play(set.id)), button("Rename", async () => {
      const title = prompt("Quiz title", set.title);
      if (!title || !title.trim()) return;
      await request("/api/mcq/sets/" + set.id, {method:"PATCH", headers:{"Content-Type":"application/json"}, body:JSON.stringify({title})});
      await library();
    }, "secondary"), button("Clear", async () => {
      if (!confirm("Clear " + set.title + "? Its storage slot will be reused.")) return;
      await request("/api/mcq/sets/" + set.id, {method:"DELETE"}); await library();
    }, "secondary danger"), button("Export JSON", async () => {
      const data = await request("/api/mcq/sets/" + set.id);
      const url = URL.createObjectURL(new Blob([JSON.stringify(data.question_set, null, 2)], {type:"application/json"}));
      const link = document.createElement("a"); link.href = url; link.download = set.title.replace(/[^a-z0-9]+/gi, "-") + ".json";
      link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    }, "secondary"));
    card.append(title, description, actions); $("sets").append(card);
  });
}
async function play(id) {
  const data = await request("/api/mcq/sets/" + id);
  activeSet = data.question_set;
  questions = activeSet.questions.map((q, i) => ({...q, id:q.id || "q" + (i+1)}));
  if (!questions.length) throw new Error("This set has no questions.");
  answers = {}; bookmarks = new Set(); index = 0; started = Date.now();
  clearInterval(timer);
  timer = setInterval(() => { $("elapsed").textContent = Math.floor((Date.now()-started)/60000) + " min elapsed"; }, 1000);
  $("quiz-title").textContent = activeSet.title; $("elapsed").textContent = "0 min elapsed";
  screen("quiz"); render();
}
function render() {
  const q = questions[index];
  $("question-counter").textContent = "Question " + (index+1) + " of " + questions.length;
  $("progress-label").textContent = Object.keys(answers).length + " / " + questions.length + " answered";
  $("progress").value = Object.keys(answers).length * 100 / questions.length;
  $("question-text").textContent = q.question;
  $("bookmark-btn").textContent = bookmarks.has(index) ? "★ Bookmarked" : "☆ Bookmark";
  $("options").replaceChildren();
  "ABCD".split("").forEach(letter => {
    const item = button(letter + ". " + q.options[letter], () => { answers[q.id] = letter; render(); }, "option" + (answers[q.id] === letter ? " selected" : ""));
    item.setAttribute("aria-pressed", answers[q.id] === letter);
    $("options").append(item);
  });
  $("prev-btn").disabled = index === 0; $("next-btn").disabled = index === questions.length-1;
  $("question-grid").replaceChildren();
  questions.forEach((q, i) => $("question-grid").append(button(String(i+1), () => {index=i;render();},
    (i===index ? "current " : "") + (answers[q.id] ? "answered " : "") + (bookmarks.has(i) ? "bookmarked" : ""))));
}
async function generate(event) {
  event.preventDefault();
  if (busy) return;
  busy=true; $("generate-btn").disabled=true; status("Generating questions from your notes. This may take a few minutes…");
  try {
    const data = await request("/api/mcq/sets/generate", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({
      topic_query:$("topic").value.trim(), num_questions:Number($("num-questions").value),
      page_title:$("page-select").value || null, title:$("set-title").value.trim() || null
    })});
    await library();
    status("Saved " + data.generated_count + " unique questions. Requested " + data.requested_count +
      "; source capacity: " + data.capacity + " from " + data.unique_chunks + " unique chunks.");
  } catch (error) { status(error.message, true); }
  finally {busy=false; $("generate-btn").disabled=false;}
}
async function submit() {
  if (!confirm("Submit your answers? " + (questions.length-Object.keys(answers).length) + " unanswered.")) return;
  $("submit-btn").disabled=true;
  try {
    const result = await request("/api/mcq/sets/" + activeSet.id + "/submit", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({answers, revision:activeSet.revision || null})});
    clearInterval(timer); screen("results");
    $("result-score").textContent = result.correct + " / " + result.total + " · " + result.percentage + "%";
    $("result-details").textContent = activeSet.title + " · " + result.unanswered + " unanswered";
    $("review").replaceChildren(); $("review").hidden=true;
    result.review.forEach((q, i) => {
      const card=document.createElement("article");card.className="panel review-item";
      const title=document.createElement("h2");title.textContent=(i+1)+". "+q.question;
      const result=document.createElement("p");result.className=q.correct?"correct":"incorrect";
      result.textContent=q.correct?"Correct":"Your answer: "+(q.selected || "Unanswered");
      card.append(title,result);
      "ABCD".split("").forEach(letter => {
        const option=document.createElement("p");option.textContent=letter+". "+q.options[letter];
        if(letter===q.answer)option.className="correct";card.append(option);
      });
      const explanation=document.createElement("p");explanation.textContent=q.explanation || "";card.append(explanation);
      $("review").append(card);
    });
  } catch(error){status(error.message,true);}
  finally{$("submit-btn").disabled=false;}
}
document.addEventListener("DOMContentLoaded", async () => {
  $("generate-form").onsubmit=generate;
  $("prev-btn").onclick=()=>{if(index>0){index--;render();}};
  $("next-btn").onclick=()=>{if(index<questions.length-1){index++;render();}};
  $("bookmark-btn").onclick=()=>{bookmarks.has(index)?bookmarks.delete(index):bookmarks.add(index);render();};
  $("submit-btn").onclick=submit;
  $("review-btn").onclick=()=>{$("review").hidden=!$("review").hidden;};
  $("retry-btn").onclick=()=>play(activeSet.id).catch(error=>status(error.message,true));
  $("library-btn").onclick=()=>{screen("library");library().catch(error=>status(error.message,true));};
  try {
    const data=await request("/api/notion-pages");
    const selected=new URLSearchParams(location.search).get("page_title");
    (data.pages || []).forEach(page=>{
      const option=document.createElement("option");option.value=page.title;option.textContent=page.title;
      option.selected=page.title===selected;$("page-select").append(option);
    });
  }catch(error){status("Could not load source pages: " + error.message,true);}
  // Saved quizzes remain accessible even if loading Notion pages fails.
  try {
    await library();
    const setId=new URLSearchParams(location.search).get("set_id");if(setId)await play(setId);
  }catch(error){status(error.message,true);}
});
