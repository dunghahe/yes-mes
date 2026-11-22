document.addEventListener("click", (event) => {
  const dialog = document.querySelector("[data-delivery-dialog]");
  if (!dialog) return;
  const opener = event.target.closest("[data-open-delivery]");
  if (opener && !opener.disabled) {
    dialog.querySelector("[data-delivery-form]").action = `/warehouse/blank-requests/${opener.dataset.id}/delivery`;
    dialog.querySelector("[data-delivery-version]").value = opener.dataset.version;
    dialog.querySelector("[data-delivery-request]").textContent = opener.dataset.reqNo;
    dialog.querySelector("[data-delivery-po]").textContent = opener.dataset.po;
    dialog.showModal();
  } else if (event.target.closest("[data-close-delivery]") || event.target === dialog) {
    dialog.close();
  }
});
