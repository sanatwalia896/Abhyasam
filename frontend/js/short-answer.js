document.addEventListener("DOMContentLoaded",()=>{
 const S=window.Study,$=id=>document.getElementById(id);let busy=false,activeSession=null;
 S.pages().catch(e=>S.status(e.message,true));
 async function run(action){if(busy)return;busy=true;$("loading").classList.remove("hidden");$("start-quiz-btn").disabled=true;$("submit-answer-btn").disabled=true;try{await action();S.status("");}catch(e){S.status(e.message,true);}finally{busy=false;$("loading").classList.add("hidden");$("submit-answer-btn").disabled=false;$("start-quiz-btn").disabled=!$("answer-form").hidden&&!$("quiz-container").hidden;}}
 $("start-form").onsubmit=event=>{event.preventDefault();run(async()=>{
 const session=S.session("short-answer");
 const result=await S.request("/api/short-answer/sessions",{num_questions:Number($("num-questions").value),session_id:session,page_title:$("page-select").value||null});
 activeSession=session;
 $("quiz-messages").replaceChildren();$("quiz-container").hidden=false;$("answer-form").hidden=false;
 $("quiz-progress").textContent="Question 1 of "+result.total_questions;S.message("quiz-messages","ai",result.question);
 });};
 $("answer-form").onsubmit=event=>{event.preventDefault();const answer=$("answer-input").value.trim();if(!answer)return;run(async()=>{
 const result=await S.request("/api/short-answer/answers",{answer,session_id:activeSession});
 S.message("quiz-messages","user",answer);S.message("quiz-messages","ai",result.previous_feedback+" · "+result.previous_score+"/10");$("answer-input").value="";
 if(result.status==="complete"){$("answer-form").hidden=true;$("quiz-progress").textContent="Practice complete";S.message("quiz-messages","ai",result.message);}
 else{$("quiz-progress").textContent="Question "+result.question_number+" of "+result.total_questions;S.message("quiz-messages","ai",result.question);}
 });};
});
