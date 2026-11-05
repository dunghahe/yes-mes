document.addEventListener("DOMContentLoaded", () => {
  const dates = document.getElementById("schedule-dates");
  const addButton = document.getElementById("add-schedule-date");
  if (!dates || !addButton) return;

  addButton.addEventListener("click", () => {
    if (dates.querySelectorAll('input[name="production_dates"]').length >= 62) return;
    const input = document.createElement("input");
    input.type = "date";
    input.name = "production_dates";
    input.required = true;
    input.setAttribute("aria-label", "Ngày sản xuất bổ sung");
    dates.append(input);
    input.focus();
  });
});
