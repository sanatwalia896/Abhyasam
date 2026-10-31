document.addEventListener("DOMContentLoaded",()=>{
 const S=window.Study,$=id=>document.getElementById(id);
 const update=()=>{$("quiz-link").href="/quiz.html"+($("page-select").value?"?page_title="+encodeURIComponent($("page-select").value):"");};
 S.pages().then(update).catch(e=>S.status(e.message,true));$("page-select").onchange=update;
 $("refresh-btn").onclick=async()=>{ $("refresh-btn").disabled=true;try{S.status("Syncing notes…");await S.request("/api/refresh-notion",{});await S.pages();update();S.status("Notes synced.");}catch(e){S.status(e.message,true);}finally{$("refresh-btn").disabled=false;} };
 $("chat-form").onsubmit=async event=>{
 event.preventDefault();if($("send-btn").disabled)return;
 const question=$("question-input").value.trim();if(!question)return;
 $("send-btn").disabled=true;$("loading").classList.remove("hidden");S.message("chat-area","user",question);
 try{const result=await S.request("/api/chat",{question,session_id:S.session("chat"),page_title:$("page-select").value||null});S.message("chat-area","ai",result.answer);$("question-input").value="";S.status("");}
 catch(e){S.status(e.message,true);}finally{$("send-btn").disabled=false;$("loading").classList.add("hidden");}
 };
});
