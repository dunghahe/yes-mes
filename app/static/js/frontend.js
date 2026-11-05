htmx.config.allowEval = false;
htmx.config.allowScriptTags = false;
htmx.config.includeIndicatorStyles = false;

document.body.addEventListener("htmx:afterSwap", (event) => {
  if (event.detail.target?.id !== "queue-fragment") return;
  const count = event.detail.target.querySelector(".table-wrap")?.dataset.queueCount;
  const badge = document.getElementById("queue-count");
  if (count !== undefined && badge) badge.textContent = count;
});
