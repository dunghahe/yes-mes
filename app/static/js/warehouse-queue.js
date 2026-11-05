document.addEventListener("DOMContentLoaded", () => {
  const queue = document.getElementById("queue-fragment");
  const badge = document.getElementById("queue-count");
  const refreshButton = document.getElementById("refresh-queue");
  if (!queue || !badge) return;

  const refresh = async () => {
    try {
      const response = await fetch(queue.dataset.queueUrl, {
        headers: { "X-Requested-With": "fetch" },
        credentials: "same-origin",
      });
      if (!response.ok || !response.headers.get("content-type")?.includes("text/html")) return;
      const fragment = await response.text();
      const documentFragment = new DOMParser().parseFromString(fragment, "text/html");
      const table = documentFragment.querySelector(".table-wrap");
      if (!table) return;
      const nextCount = Number(table.dataset.queueCount || 0);
      queue.replaceChildren(table);
      queue.dataset.count = String(nextCount);
      badge.textContent = String(nextCount);
    } catch {
      badge.setAttribute("aria-label", "Không thể làm mới hàng chờ");
    }
  };

  refreshButton?.addEventListener("click", refresh);
  window.setInterval(() => {
    if (!document.hidden) refresh();
  }, 15000);
});
