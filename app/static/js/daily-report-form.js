const poSuggestionTimers = new WeakMap();
const poSuggestionRequests = new WeakMap();

const closePoSuggestions = (input) => {
  const list = document.getElementById(input.getAttribute("aria-controls"));
  if (list) list.hidden = true;
  input.setAttribute("aria-expanded", "false");
};

const loadPoSuggestions = (input) => {
  clearTimeout(poSuggestionTimers.get(input));
  poSuggestionRequests.get(input)?.abort();
  const query = input.value.trim();
  if (!query) {
    closePoSuggestions(input);
    return;
  }
  poSuggestionTimers.set(input, setTimeout(async () => {
    const controller = new AbortController();
    poSuggestionRequests.set(input, controller);
    const params = new URLSearchParams({ field: "po", q: query });
    try {
      const response = await fetch(`/daily-reports/suggestions?${params}`, {
        credentials: "same-origin",
        signal: controller.signal,
        headers: { Accept: "application/json" },
      });
      if (!response.ok || input.value.trim() !== query) return;
      const payload = await response.json();
      const list = document.getElementById(input.getAttribute("aria-controls"));
      if (!list) return;
      list.replaceChildren(...payload.suggestions.map((value) => {
        const option = document.createElement("button");
        option.type = "button";
        option.className = "search-suggestion-option";
        option.setAttribute("role", "option");
        option.setAttribute("aria-selected", "false");
        option.dataset.poSuggestion = "true";
        option.dataset.value = value;
        option.textContent = value;
        return option;
      }));
      list.hidden = payload.suggestions.length === 0;
      input.setAttribute("aria-expanded", String(payload.suggestions.length > 0));
    } catch (error) {
      if (error.name !== "AbortError") closePoSuggestions(input);
    }
  }, 180));
};

document.addEventListener("input", (event) => {
  const input = event.target.closest("[data-po-suggest]");
  if (input) loadPoSuggestions(input);
});

document.addEventListener("click", (event) => {
  const option = event.target.closest("[data-po-suggestion]");
  if (option) {
    const input = document.getElementById("report-po-filter");
    if (input) {
      input.value = option.dataset.value;
      closePoSuggestions(input);
      input.form?.requestSubmit();
    }
    return;
  }
  if (!event.target.closest(".suggestion-input-wrap")) {
    document.querySelectorAll("[data-po-suggest]").forEach(closePoSuggestions);
  }

  const addDowntime = event.target.closest("[data-add-downtime]");
  if (addDowntime) {
    const card = addDowntime.closest("[data-report-pair-card]");
    const row = card.querySelector("[data-downtime-template]").content.firstElementChild.cloneNode(true);
    card.querySelector("[data-downtime-list]").append(row);
    const checkbox = card.querySelector("[data-downtime-recorded]");
    checkbox.checked = true;
    checkbox.closest(".report-optional-section")?.classList.add("has-downtime-record");
    row.querySelector("select")?.focus();
    return;
  }

  const removeDowntime = event.target.closest("[data-remove-entry]");
  if (removeDowntime) removeDowntime.closest(".report-entry-row").remove();
});

document.addEventListener("change", (event) => {
  const checkbox = event.target.closest("[data-downtime-recorded]");
  if (!checkbox) return;
  checkbox.closest(".report-optional-section")?.classList.toggle("has-downtime-record", checkbox.checked);
});

document.addEventListener("mousedown", (event) => {
  if (event.target.closest("[data-po-suggestion]")) event.preventDefault();
});

document.addEventListener("keydown", (event) => {
  const input = event.target.closest("[data-po-suggest]");
  if (input && event.key === "ArrowDown") {
    const list = document.getElementById(input.getAttribute("aria-controls"));
    const first = list?.querySelector("[data-po-suggestion]");
    if (first) {
      event.preventDefault();
      first.focus();
    }
    return;
  }
  if (input && event.key === "Escape") {
    closePoSuggestions(input);
    return;
  }

  const option = event.target.closest("[data-po-suggestion]");
  if (!option) return;
  const list = option.closest("[role=listbox]");
  const options = [...list.querySelectorAll("[data-po-suggestion]")];
  const index = options.indexOf(option);
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    options[(index + (event.key === "ArrowDown" ? 1 : options.length - 1)) % options.length]?.focus();
  } else if (event.key === "Escape") {
    const search = document.getElementById("report-po-filter");
    if (search) {
      closePoSuggestions(search);
      search.focus();
    }
  } else if (event.key === "Enter") {
    event.preventDefault();
    option.click();
  }
});

document.querySelectorAll("[data-daily-report-form]").forEach((form) => {
  const raw = form.querySelector("[name=report_payload]")?.value;
  if (!raw) return;
  try {
    const payload = JSON.parse(raw);
    form.querySelector("[data-report-date]").value = payload.report_date || "";
    const shift = payload.shifts?.[0];
    if (!shift) return;
    form.querySelector("[data-shift-id]").value = shift.shift_id;
    form.querySelectorAll("[data-report-pair-card]").forEach((card) => {
      const pair = shift.pairs?.find((item) => String(item.source_machine_pair_id) === card.dataset.sourceMachinePairId);
      if (!pair) return;
      const employee = card.querySelector("[data-employee-id]");
      employee.value = pair.employee_id;
      employee.dispatchEvent(new Event("change", { bubbles: true }));
      card.querySelector("[data-quantity]").value = pair.quantity_produced;
      card.querySelector("[data-downtime-recorded]").checked = Boolean(pair.downtime_recorded);
      const list = card.querySelector("[data-downtime-list]");
      list.replaceChildren();
      (pair.downtime || []).forEach((entry) => {
        const row = card.querySelector("[data-downtime-template]").content.firstElementChild.cloneNode(true);
        row.querySelector("[data-reason-id]").value = entry.reason_id;
        row.querySelector("[data-downtime-minutes]").value = entry.minutes;
        list.append(row);
      });
      const details = card.querySelector("details");
      details.open = Boolean(pair.downtime_recorded || pair.downtime?.length);
      details.classList.toggle("has-downtime-record", Boolean(pair.downtime_recorded));
    });
  } catch {
    // A malformed request must not interrupt the rest of the page.
  }
});

document.addEventListener("submit", (event) => {
  const form = event.target.closest("[data-daily-report-form]");
  if (!form) return;

  const payload = {
    blank_request_id: Number(form.querySelector("[data-blank-request-id]").value),
    report_date: form.querySelector("[data-report-date]").value,
    shifts: [...form.querySelectorAll("[data-shift-block]")].map((shiftBlock) => ({
      shift_id: Number(shiftBlock.querySelector("[data-shift-id]").value),
      pairs: [...shiftBlock.querySelectorAll("[data-report-pair-card]")].map((card) => ({
        source_machine_pair_id: Number(card.dataset.sourceMachinePairId),
        machine_pair_id: Number(card.querySelector("[data-pair-id]").value),
        employee_id: Number(card.querySelector("[data-employee-id]").value),
        downtime_recorded: card.querySelector("[data-downtime-recorded]").checked,
        quantity_produced: Number(card.querySelector("[data-quantity]").value),
        downtime: [...card.querySelectorAll("[data-downtime-list] .downtime-entry-row")].map((row) => ({
          reason_id: Number(row.querySelector("[data-reason-id]").value),
          minutes: Number(row.querySelector("[data-downtime-minutes]").value),
        })),
      })),
    })),
  };
  form.querySelector("[name=report_payload]").value = JSON.stringify(payload);
});
