const requestDialog = document.querySelector("[data-blank-request-dialog]");
const scheduleSelect = requestDialog?.querySelector('[name="schedule_id"]');
const assignmentFieldset = requestDialog?.querySelector("[data-assignment-fieldset]");
const assignmentHelp = requestDialog?.querySelector("[data-assignment-help]");
const createSubmit = requestDialog?.querySelector("[data-create-submit]");

function updateRequestTypeFields() {
  if (!scheduleSelect || !assignmentFieldset) return;
  const selectedOption = scheduleSelect.selectedOptions[0];
  const isBaviaOnly = selectedOption?.dataset.processType === "BAVIA_ONLY";
  assignmentFieldset.hidden = isBaviaOnly;
  assignmentFieldset.querySelectorAll("select").forEach((select) => {
    select.disabled = isBaviaOnly;
    const autocomplete = select.previousElementSibling?.classList.contains("employee-autocomplete")
      ? select.previousElementSibling.querySelector(".employee-autocomplete-input")
      : null;
    if (autocomplete) autocomplete.disabled = isBaviaOnly;
  });
  if (assignmentHelp) {
    assignmentHelp.textContent = isBaviaOnly
      ? "Yêu cầu Bavia chỉ cần ngày và kíp; không chọn máy."
      : "Chọn cặp máy và người làm cho từng dòng.";
    assignmentHelp.hidden = false;
  }
  const resourceWarning = requestDialog.querySelector("[data-resource-warning]");
  if (resourceWarning) resourceWarning.hidden = isBaviaOnly;
  if (createSubmit) {
    createSubmit.disabled = !selectedOption?.value
      || (!isBaviaOnly && createSubmit.dataset.hasResources !== "true");
  }
}

scheduleSelect?.addEventListener("change", updateRequestTypeFields);
updateRequestTypeFields();

if (requestDialog?.dataset.autoOpen === "true") {
  requestDialog.showModal();
}

document.addEventListener("click", (event) => {
  const openButton = event.target.closest("[data-open-blank-request]");
  if (openButton && requestDialog && !requestDialog.open) {
    requestDialog.showModal();
    requestDialog.querySelector(".employee-autocomplete-input")?.focus();
    return;
  }

  const closeButton = event.target.closest("[data-close-blank-request]");
  if (closeButton && requestDialog?.open) {
    requestDialog.close();
    return;
  }

  if (event.target === requestDialog && requestDialog.open) {
    requestDialog.close();
    return;
  }

  const addButton = event.target.closest("[data-add-assignment]");
  if (addButton) {
    const list = addButton.closest("fieldset").querySelector("[data-assignment-list]");
    const row = list.querySelector("[data-assignment-row]").cloneNode(true);
    row.querySelectorAll("select").forEach((select) => {
      select.selectedIndex = 0;
      select.id = `${select.id.split("-")[0]}-${crypto.randomUUID()}`;
      select.removeAttribute("aria-invalid");
      const picker = select.previousElementSibling?.classList.contains("employee-autocomplete")
        ? select.previousElementSibling
        : null;
      if (picker) {
        const search = picker.querySelector(".employee-autocomplete-input");
        const suggestions = picker.querySelector("[role=listbox]");
        if (search) {
          search.id = `${select.id}-search`;
          search.value = "";
          search.setCustomValidity("");
          search.setAttribute("aria-controls", `${select.id}-suggestions`);
        }
        if (suggestions) {
          suggestions.id = `${select.id}-suggestions`;
          suggestions.replaceChildren();
          suggestions.hidden = true;
        }
      }
    });
    row.querySelectorAll("label").forEach((label, index) => {
      const select = row.querySelectorAll("select")[index];
      const search = select.previousElementSibling?.querySelector(".employee-autocomplete-input");
      label.htmlFor = search?.id || select.id;
    });
    let removeButton = row.querySelector("[data-remove-assignment]");
    if (!removeButton) {
      removeButton = document.createElement("button");
      removeButton.type = "button";
      removeButton.className = "secondary-button";
      removeButton.dataset.removeAssignment = "";
      removeButton.textContent = "Xóa dòng";
      row.append(removeButton);
    }
    list.append(row);
    row.querySelector("select")?.focus();
    return;
  }

  const removeButton = event.target.closest("[data-remove-assignment]");
  if (removeButton) {
    const list = removeButton.closest("[data-assignment-list]");
    if (list.querySelectorAll("[data-assignment-row]").length > 1) {
      removeButton.closest("[data-assignment-row]").remove();
    }
  }
});
