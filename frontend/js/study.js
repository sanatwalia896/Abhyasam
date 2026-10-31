window.Study = {
  async request(path, body, method) {
    const response = await fetch(window.ABHYASAM_API_BASE + path, body === undefined ? {cache:"no-store", method:method || "GET"} : {
      method:method || "POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)
    });
    let data;
    try { data = await response.json(); } catch { throw new Error("The API returned an unreadable response ("+response.status+"). Please retry."); }
    if (!response.ok || data.status === "error") throw new Error(typeof data.detail === "string" ? data.detail : data.message || "Request failed. Please try again.");
    return data;
  },
  status(message, error=false) { const el=document.getElementById("status");el.textContent=message;el.className=error?"error":""; },
  session(mode) {
    const key="abhyasam-"+mode+":"+(document.getElementById("page-select")?.value || "all");
    if(!sessionStorage.getItem(key))sessionStorage.setItem(key,crypto.randomUUID());
    return sessionStorage.getItem(key);
  },
  async pages() {
    const data=await this.request("/api/notion-pages");
    const select=document.getElementById("page-select");
    const selected=select.value || new URLSearchParams(location.search).get("page_title");
    select.length=1;
    (data.pages||[]).forEach(page=>{const option=new Option(page.title,page.title);option.selected=page.title===selected;select.add(option);});
  },
  message(id, role, text) {
    const area=document.getElementById(id);area.querySelector(".empty")?.remove();
    const element=document.createElement("div");element.className="message "+role;element.textContent=text;
    area.append(element);area.scrollTop=area.scrollHeight;
  }
};
