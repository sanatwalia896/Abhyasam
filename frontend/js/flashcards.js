document.addEventListener("DOMContentLoaded",()=>{
 const S=window.Study,$=id=>document.getElementById(id);let cards=[],index=0,flipped=false;
 function render(){if(!cards.length)return;$("flashcard-viewer").hidden=false;
   $("flashcard-front-content").textContent=cards[index].front;$("flashcard-back-content").textContent=cards[index].back;
   $("active-flashcard").classList.toggle("is-flipped",flipped);$("flip-card").setAttribute("aria-pressed",String(flipped));
   $("front-face").setAttribute("aria-hidden",String(flipped));$("back-face").setAttribute("aria-hidden",String(!flipped));
   $("flashcard-counter").textContent=(index+1)+" / "+cards.length;$("prev-btn").disabled=index===0;$("next-btn").disabled=index===cards.length-1;
 }
 function deck(data){cards=data.flashcards;index=0;flipped=false;$("page-title-display").textContent="From: "+(data.page_title||"All notes");render();}
 let activeDeck=null;
 async function library(){
   const result=await S.request("/api/flashcard-decks");
   $("deck-library").replaceChildren();$("deck-library-count").textContent=result.decks.length+" / 10 decks";
   if(!result.decks.length)$("deck-library").textContent="No decks yet. Choose a page and generate your first deck.";
   result.decks.forEach(item=>{
     const card=document.createElement("article");card.className="set-card";
     const title=document.createElement("h3");title.textContent=item.page_title || "All notes";
     const description=document.createElement("p");description.textContent=item.card_count+" cards";
     const actions=document.createElement("div");actions.className="actions";
     const load=document.createElement("button");load.textContent="Study deck";
     load.onclick=async()=>{try{await loadDeck(item.deck_id);}catch(e){S.status(e.message,true);}};
     const remove=document.createElement("button");remove.textContent="Clear";remove.className="secondary danger";
     remove.onclick=async()=>{if(!confirm("Clear this deck? Its storage slot will be reused."))return;remove.disabled=true;
       try{await S.request("/api/flashcard-decks/"+encodeURIComponent(item.deck_id),undefined,"DELETE");
         if(activeDeck===item.deck_id){cards=[];$("flashcard-viewer").hidden=true;activeDeck=null;const url=new URL(location.href);url.searchParams.delete("deck_id");history.replaceState(null,"",url);}
         await library();S.status("Deck cleared. Its storage slot is available for a new deck.");
       }catch(e){S.status(e.message,true);remove.disabled=false;}
     };
     actions.append(load,remove);card.append(title,description,actions);$("deck-library").append(card);
   });
 }
 function setDeck(data){activeDeck=data.deck_id;deck(data);const url=new URL(location.href);url.searchParams.set("deck_id",data.deck_id);if(data.page_title)url.searchParams.set("page_title",data.page_title);history.replaceState(null,"",url);}
 async function loadDeck(id){setDeck(await S.request("/api/flashcards?deck_id="+encodeURIComponent(id)));}
 library().catch(e=>S.status(e.message,true));
 S.pages().catch(e=>S.status(e.message,true));
 const deckId=new URLSearchParams(location.search).get("deck_id");
 if(deckId)loadDeck(deckId).catch(e=>S.status(e.message,true));
 $("deck-form").onsubmit=async event=>{event.preventDefault();if($("generate-btn").disabled)return;$("generate-btn").disabled=true;S.status("Generating flashcards for "+$("page-select").value+"…");
 try{const data=await S.request("/api/generate-flashcards",{topic_query:$("page-select").value,page_title:$("page-select").value,num_batches:1,flashcards_per_batch:Number($("card-count").value)});setDeck(data);await library();S.status("Deck saved. Click a card to reveal its answer.");}
 catch(e){S.status(e.message,true);}finally{$("generate-btn").disabled=false;}
 };
 $("flip-card").onclick=()=>{flipped=!flipped;render();};
 $("prev-btn").onclick=()=>{if(index>0){index--;flipped=false;render();}};
 $("next-btn").onclick=()=>{if(index<cards.length-1){index++;flipped=false;render();}};
});
