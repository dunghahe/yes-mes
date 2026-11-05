document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("print-form")?.addEventListener("click", () => window.print());
  if (document.body.dataset.autoPrint === "true") {
    window.setTimeout(() => window.print(), 300);
  }
});
