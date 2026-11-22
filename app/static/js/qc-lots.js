const refreshLotQcForm = (form) => {
  const ng = Number(form.querySelector("[data-qc-ng]")?.value || 0);
  const details = form.querySelector("[data-defect-section]");
  if (!details) return;
  details.hidden = ng === 0;
  details.querySelectorAll("input, select").forEach((control) => {
    control.disabled = details.hidden || details.dataset.readonly === "true";
  });

  const rows = [...form.querySelectorAll("[data-defect-list] tr")];
  const defectTotal = ng === 0 ? 0 : rows.reduce((sum, row) => sum + Number(row.querySelector("[name=defect_quantity]")?.value || 0), 0);
  const quantityIn = Number(form.querySelector("[data-lot-qc-balance]").dataset.quantityIn);
  const ok = Number(form.querySelector("[data-qc-ok]")?.value || 0);
  const balance = form.querySelector("[data-lot-qc-balance]");
  const countsMatch = ok + ng === quantityIn;
  const detailsMatch = ng === defectTotal;
  balance.hidden = !form.querySelector("[data-qc-ok]")?.value
    && !form.querySelector("[data-qc-ng]")?.value;
  const difference = quantityIn - ok - ng;
  balance.textContent = countsMatch && detailsMatch
    ? "OK + NG đã khớp số lượng lô."
    : !countsMatch
      ? (difference > 0 ? `Còn thiếu ${difference} con.` : `Vượt số lượng lô ${-difference} con.`)
      : `Chi tiết NG: đã phân loại ${defectTotal}/${ng} con.`;
  balance.classList.toggle("is-valid", countsMatch && detailsMatch);
  balance.classList.toggle("is-invalid", !countsMatch || !detailsMatch);
};

const suggestionTimers = new WeakMap();
const suggestionRequests = new WeakMap();

const closeSuggestions = (input) => {
  const list = document.getElementById(input.getAttribute("aria-controls"));
  if (list) list.hidden = true;
  input.setAttribute("aria-expanded", "false");
};

const chooseSuggestion = (input, option) => {
  input.value = option.dataset.value;
  closeSuggestions(input);
  input.form?.requestSubmit();
};

const loadSearchSuggestions = (input) => {
  clearTimeout(suggestionTimers.get(input));
  suggestionRequests.get(input)?.abort();
  const query = input.value.trim();
  if (!query) {
    closeSuggestions(input);
    return;
  }
  suggestionTimers.set(input, setTimeout(async () => {
    const controller = new AbortController();
    suggestionRequests.set(input, controller);
    const params = new URLSearchParams({ field: input.dataset.searchSuggest, q: query });
    try {
      const response = await fetch(`/qc/suggestions?${params}`, {
        credentials: "same-origin",
        signal: controller.signal,
        headers: { Accept: "application/json" },
      });
      if (!response.ok) return;
      const payload = await response.json();
      if (input.value.trim() !== query) return;
      const list = document.getElementById(input.getAttribute("aria-controls"));
      if (!list) return;
      list.replaceChildren(...payload.suggestions.map((value) => {
        const option = document.createElement("button");
        option.type = "button";
        option.className = "search-suggestion-option";
        option.setAttribute("role", "option");
        option.setAttribute("aria-selected", "false");
        option.dataset.suggestionOption = "true";
        option.dataset.value = value;
        option.textContent = value;
        return option;
      }));
      list.hidden = payload.suggestions.length === 0;
      input.setAttribute("aria-expanded", String(payload.suggestions.length > 0));
    } catch (error) {
      if (error.name !== "AbortError") console.warn("Không tải được gợi ý tìm kiếm.");
    }
  }, 180));
};

document.addEventListener("click", (event) => {
  const suggestion = event.target.closest("[data-suggestion-option]");
  if (suggestion) {
    const list = suggestion.closest("[role=listbox]");
    const input = document.querySelector(`[aria-controls="${list.id}"]`);
    if (input) chooseSuggestion(input, suggestion);
    return;
  }
  if (!event.target.closest(".suggestion-input-wrap")) {
    document.querySelectorAll("[data-search-suggest]").forEach(closeSuggestions);
  }
  const add = event.target.closest("[data-add-defect]");
  if (add) {
    const form = add.closest("[data-lot-qc-form]");
    const row = add.closest("fieldset").querySelector("[data-defect-template]").content.firstElementChild.cloneNode(true);
    add.closest("fieldset").querySelector("[data-defect-list]").append(row);
    row.querySelector("select")?.focus();
    refreshLotQcForm(form);
    return;
  }
  const remove = event.target.closest("[data-remove-defect]");
  if (remove) {
    const form = remove.closest("[data-lot-qc-form]");
    remove.closest("tr").remove();
    refreshLotQcForm(form);
  }
});

document.addEventListener("input", (event) => {
  if (event.target.matches("[data-search-suggest]")) loadSearchSuggestions(event.target);
  const form = event.target.closest("[data-lot-qc-form]");
  if (form) refreshLotQcForm(form);
});

document.addEventListener("mousedown", (event) => {
  if (event.target.closest("[data-suggestion-option]")) event.preventDefault();
});

document.addEventListener("keydown", (event) => {
  const input = event.target.closest("[data-search-suggest]");
  if (input && event.key === "ArrowDown") {
    const list = document.getElementById(input.getAttribute("aria-controls"));
    const first = list?.querySelector("[data-suggestion-option]");
    if (first) {
      event.preventDefault();
      first.focus();
    }
    return;
  }
  const option = event.target.closest("[data-suggestion-option]");
  if (!option) return;
  const list = option.closest("[role=listbox]");
  const options = [...list.querySelectorAll("[data-suggestion-option]")];
  const index = options.indexOf(option);
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    options[(index + (event.key === "ArrowDown" ? 1 : options.length - 1)) % options.length]?.focus();
  } else if (event.key === "Escape") {
    const inputElement = document.querySelector(`[aria-controls="${list.id}"]`);
    if (inputElement) {
      closeSuggestions(inputElement);
      inputElement.focus();
    }
  } else if (event.key === "Enter") {
    event.preventDefault();
    const inputElement = document.querySelector(`[aria-controls="${list.id}"]`);
    if (inputElement) chooseSuggestion(inputElement, option);
  }
});

document.addEventListener("change", (event) => {
  const form = event.target.closest("[data-lot-qc-form]");
  if (form) refreshLotQcForm(form);
});

document.addEventListener("DOMContentLoaded", () => {
  const form = document.querySelector("[data-lot-qc-form]");
  if (form) refreshLotQcForm(form);
});
