htmx.config.allowEval = false;
htmx.config.allowScriptTags = false;
htmx.config.includeIndicatorStyles = false;

const updateLotCountPreview = (root = document) => {
  root.querySelectorAll("[data-lot-preview]").forEach((preview) => {
    const quantity = Number(document.getElementById(preview.dataset.quantityId)?.value);
    const lotSize = Number(document.getElementById(preview.dataset.sizeId)?.value);
    const countNode = preview.querySelector("[data-lot-count]");
    const breakdownNode = preview.querySelector("[data-lot-breakdown]");
    if (!Number.isSafeInteger(quantity) || quantity < 1 || !Number.isSafeInteger(lotSize) || lotSize < 1) {
      preview.hidden = true;
      return;
    }
    const lotCount = Math.ceil(quantity / lotSize);
    const fullLots = Math.floor(quantity / lotSize);
    const remainder = quantity % lotSize;
    countNode.textContent = `${lotCount} lô`;
    breakdownNode.textContent = remainder
      ? `${fullLots} lô × ${lotSize} · lô cuối ${remainder}`
      : `${lotCount} lô × ${lotSize}`;
    preview.hidden = false;
  });
};

document.addEventListener("input", (event) => {
  if (event.target.matches('[name="ordered_quantity"], [name="lot_size"]')) updateLotCountPreview();
});
document.addEventListener("DOMContentLoaded", () => updateLotCountPreview());
updateLotCountPreview();

let previousQueueIds = null;

document.body.addEventListener("htmx:afterSwap", (event) => {
  if (event.detail.target?.id !== "queue-fragment") return;
  const count = event.detail.target.querySelector(".table-wrap")?.dataset.queueCount;
  const badge = document.getElementById("queue-count");
  if (count !== undefined && badge) badge.textContent = count;
  const currentIds = new Set(
    [...event.detail.target.querySelectorAll("tr[data-request-id]")].map((row) => row.dataset.requestId),
  );
  if (previousQueueIds !== null) {
    const newRows = [...event.detail.target.querySelectorAll("tr[data-request-id]")].filter(
      (row) => !previousQueueIds.has(row.dataset.requestId),
    );
    newRows.forEach((row) => row.classList.add("queue-row-new"));
  }
  previousQueueIds = currentIds;
});
