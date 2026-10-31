document.addEventListener("DOMContentLoaded", () => {
  const api = window.ABHYASAM_API_BASE;
  const select = document.getElementById("page-select");
  const status = document.getElementById("status");
  const refresh = document.getElementById("refresh-btn");
  const flashcards = document.getElementById("flashcards-btn");
  function show(message, error = false) { status.textContent = message; status.className = error ? "error" : ""; }
  async function request(path, options = {}) {
    const response = await fetch(api + path, {cache:"no-store", ...options});
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Request failed (" + response.status + ")");
    return data;
  }
  function updateLinks() {
    const query = select.value ? "?page_title=" + encodeURIComponent(select.value) : "";
    document.getElementById("quiz-btn").href = "/quiz.html" + query;
    document.getElementById("mcq-card").href = "/quiz.html" + query;
    document.getElementById("chat-btn").href = "/chat.html" + query;
    document.getElementById("short-answer-link").href = "/short-answer.html" + query;
  }
  async function loadPages() {
    const previous = select.value || new URLSearchParams(location.search).get("page_title") || "";
    const data = await request("/api/notion-pages");
    select.replaceChildren(new Option("All synced pages", ""));
    (data.pages || []).forEach(page => select.add(new Option(page.title, page.title)));
    select.value = previous;
    document.getElementById("page-count").textContent = (data.pages || []).length + " synced pages";
    updateLinks();
    show((data.pages || []).length ? "Choose a page for focused practice, or explore all your notes." : "No synced pages yet. Sync notes to add your source material. Saved quizzes are still available.");
  }
  select.addEventListener("change", updateLinks);
  refresh.addEventListener("click", async () => {
    refresh.disabled = true; show("Syncing your Notion notes…");
    try {
      const summary = await request("/api/refresh-notion", {method:"POST"});
      await loadPages();
      show("Synced " + summary.changed + " changed pages; " + summary.skipped + " unchanged." + (summary.failed ? " " + summary.failed + " pages failed; check backend logs." : ""));
    } catch (error) { show(error.message, true); }
    finally { refresh.disabled=false; }
  });
  flashcards.addEventListener("click", () => {
    location.href = "/flashcards.html" + (select.value ? "?page_title=" + encodeURIComponent(select.value) : "");
  });
  loadPages().catch(error => {
    document.getElementById("page-count").textContent="Connection unavailable";
    show("Could not load pages: " + error.message + ". You can still open the quiz library.",true);
  });
});
