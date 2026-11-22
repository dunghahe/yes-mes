document.addEventListener("DOMContentLoaded", () => {
  const dayDialog = document.getElementById("schedule-day-dialog");
  const dayContent = document.getElementById("schedule-day-content");
  const dayTitle = document.getElementById("schedule-day-title");
  document.addEventListener("click", (event) => {
    const opener = event.target.closest("[data-open-schedule-day]");
    if (opener && dayDialog) {
      dayTitle.textContent = opener.dataset.dayTitle;
      if (!dayDialog.open) dayDialog.showModal();
      return;
    }
    if (event.target.closest("[data-close-schedule-day]") || event.target === dayDialog) {
      dayDialog?.close();
      return;
    }
    const editButton = event.target.closest("[data-day-schedule-edit]");
    if (editButton) openEdit(editButton);
  });
  document.body.addEventListener("htmx:beforeRequest", (event) => {
    if (event.detail.target?.id === "schedule-day-content") {
      dayContent.textContent = "Đang tải lịch…";
    }
  });
  const showDayError = (event) => {
    if (event.detail.target?.id === "schedule-day-content") {
      dayContent.textContent = "Không tải được lịch. Đóng và mở lại ngày để thử lại.";
    }
  };
  document.body.addEventListener("htmx:responseError", showDayError);
  document.body.addEventListener("htmx:sendError", showDayError);

  const dates = document.getElementById("schedule-dates");
  const addButton = document.getElementById("add-schedule-date");
  const form = document.getElementById("schedule-form");
  const modalTitle = document.getElementById("schedule-modal-title");
  const version = document.getElementById("schedule-version");
  const formMode = document.getElementById("schedule-form-mode");
  const deleteForm = document.getElementById("schedule-delete-form");
  const warning = document.getElementById("schedule-past-date-warning");
  if (!dates || !addButton || !form) return;

  const addRemoveButton = (input) => {
    const row = document.createElement("div");
    row.className = "schedule-date-row";
    input.parentNode.insertBefore(row, input);
    row.append(input);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "secondary-button schedule-date-remove";
    remove.textContent = "Xóa ngày";
    remove.setAttribute("aria-label", "Xóa ngày sản xuất này");
    remove.addEventListener("click", () => row.remove());
    row.append(remove);
  };

  const getDateInputs = () => [...dates.querySelectorAll("input[type=date]")];
  const clearAdditionalDates = () => {
    getDateInputs().slice(1).forEach((input) => {
      const row = input.closest(".schedule-date-row");
      if (row) row.remove();
      else input.remove();
    });
  };
  const localToday = () => {
    const today = new Date();
    return `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  };
  const updatePastWarning = () => {
    if (!warning) return;
    warning.hidden = !getDateInputs().some((input) => input.value && input.value < localToday());
  };
  const setSelectValue = (select, value) => {
    select.value = value;
    const search = select.previousElementSibling?.querySelector(".employee-autocomplete-input");
    if (search) {
      const option = select.selectedOptions[0];
      search.value = option?.dataset.selectedLabel || option?.textContent?.trim() || "";
      search.setCustomValidity("");
    }
    select.dispatchEvent(new Event("change", { bubbles: true }));
  };
  const openModal = () => window.dispatchEvent(new Event("open-schedule"));
  const openCreate = () => {
    clearAdditionalDates();
    const firstDate = getDateInputs()[0];
    firstDate.name = "production_dates";
    firstDate.value = document.getElementById("open-schedule-create")?.dataset.date || "";
    form.action = "/schedules";
    form.setAttribute("action", "/schedules");
    form.dataset.mode = "create";
    if (formMode) formMode.value = "create";
    version.value = "";
    if (deleteForm) deleteForm.hidden = true;
    addButton.hidden = false;
    modalTitle.textContent = "Tạo lịch sản xuất";
    setSelectValue(document.getElementById("schedule-shift"), document.getElementById("open-schedule-create")?.dataset.shiftId || "");
    setSelectValue(document.getElementById("schedule-order"), "");
    document.getElementById("planned-quantity").value = "";
    updatePastWarning();
    openModal();
  };
  const initialDates = getDateInputs();
  if (initialDates[0]?.name === "production_dates") initialDates.slice(1).forEach(addRemoveButton);
  if (initialDates[0]?.name === "production_date") addButton.hidden = true;
  updatePastWarning();

  addButton.addEventListener("click", () => {
    if (dates.querySelectorAll('input[name="production_dates"]').length >= 62) return;
    const input = document.createElement("input");
    input.type = "date";
    input.name = "production_dates";
    input.required = true;
    input.setAttribute("aria-label", "Ngày sản xuất bổ sung");
    addRemoveButton(input);
    input.focus();
  });

  dates.addEventListener("input", updatePastWarning);
  dates.addEventListener("change", updatePastWarning);
  document.getElementById("open-schedule-create")?.addEventListener("click", openCreate);
  function openEdit(card) {
    if (!card || !card.dataset.id || !form) return;
    if (dayDialog?.open) dayDialog.close();
    clearAdditionalDates();
    const firstDate = getDateInputs()[0];
    firstDate.name = "production_date";
    firstDate.value = card.dataset.date;
    const editUrl = card.dataset.editUrl || `/schedules/${card.dataset.id}`;
    form.action = editUrl;
    form.setAttribute("action", editUrl);
    form.dataset.mode = "edit";
    if (formMode) formMode.value = "edit";
    version.value = card.dataset.version;
    if (deleteForm) {
      deleteForm.action = card.dataset.deleteUrl || `/schedules/${card.dataset.id}/delete`;
      deleteForm.hidden = false;
    }
    addButton.hidden = true;
    modalTitle.textContent = "Sửa lịch sản xuất";
    setSelectValue(document.getElementById("schedule-shift"), card.dataset.shiftId);
    setSelectValue(document.getElementById("schedule-order"), card.dataset.orderId);
    document.getElementById("planned-quantity").value = card.dataset.quantity;
    updatePastWarning();
    openModal();
  }

  document.addEventListener("dblclick", (event) => {
    openEdit(event.target.closest("[data-edit-schedule]"));
  });
  document.addEventListener("keydown", (event) => {
    const card = event.target.closest("[data-edit-schedule]");
    if (!card || (event.key !== "Enter" && event.key !== " ")) return;
    event.preventDefault();
    openEdit(card);
  });
  form.addEventListener("submit", (event) => {
    const expectedMode = form.dataset.mode;
    const requestedMode = formMode?.value;
    const actionPath = new URL(form.action, window.location.href).pathname;
    const isExpectedAction = expectedMode === "edit"
      ? /^\/schedules\/\d+$/.test(actionPath)
      : actionPath === "/schedules";
    if (requestedMode !== expectedMode || !isExpectedAction) {
      event.preventDefault();
      window.alert("Không thể xác định đúng lịch cần sửa. Hãy đóng form và mở lại lịch.");
    }
  });
});
