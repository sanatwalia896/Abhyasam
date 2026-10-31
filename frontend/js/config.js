// One API address for every screen. Override ABHYASAM_API_BASE before loading
// this script when hosting the frontend separately in production.
window.ABHYASAM_API_BASE = window.ABHYASAM_API_BASE || (
  ["3000", "5500"].includes(window.location.port)
    ? `${window.location.protocol}//${window.location.hostname}:8000`
    : window.location.origin
);

document.addEventListener("DOMContentLoaded", () => {
  function updateNavigation(pageOverride) {
    const page = pageOverride === undefined ? (document.getElementById("page-select")?.value || new URLSearchParams(location.search).get("page_title")) : pageOverride;
    document.querySelectorAll(".mode-nav a").forEach(link => {
      const url = new URL(link.getAttribute("href"), location.origin);
      if (page) url.searchParams.set("page_title", page); else url.searchParams.delete("page_title");
      link.href = url.pathname + url.search;
      if (url.pathname === location.pathname) link.setAttribute("aria-current", "page");
    });
  }
  updateNavigation();
  document.addEventListener("change", event => {if (event.target.id === "page-select") updateNavigation(event.target.value);});
});
