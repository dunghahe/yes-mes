(() => {
  let pickerNumber = 0;
  const typeLabels = {
    operator: "Công nhân",
    engineering: "Kỹ thuật",
    qc: "QC",
    repair: "Sửa chữa",
  };

  const normalize = (value) => value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLocaleLowerCase("vi")
    .trim();

  const optionLabel = (option) => option.textContent.trim();
  const selectedLabel = (option) => option.dataset.selectedLabel || optionLabel(option);

  function initialize(select) {
    if (select.dataset.employeeAutocompleteReady === "true") return;
    select.dataset.employeeAutocompleteReady = "true";
    pickerNumber += 1;

    const id = select.id || `employee-select-${pickerNumber}`;
    select.id = id;
    const searchId = `${id}-search`;
    const listId = `${id}-suggestions`;
    const explicitLabel = document.querySelector(`label[for="${CSS.escape(id)}"]`);
    const wrappingLabel = select.closest("label");
    const labelText = select.dataset.autocompleteLabel
      || select.getAttribute("aria-label")
      || explicitLabel?.textContent.trim()
      || [...(wrappingLabel?.childNodes || [])]
        .filter((node) => node.nodeType === Node.TEXT_NODE)
        .map((node) => node.textContent.trim())
        .filter(Boolean)
        .join(" ")
      || "nhân viên";

    const wrapper = document.createElement("div");
    wrapper.className = "employee-autocomplete";
    const search = document.createElement("input");
    search.id = searchId;
    search.type = "search";
    search.className = "employee-autocomplete-input";
    search.placeholder = select.dataset.autocompletePlaceholder || "Gõ mã hoặc tên để tìm…";
    search.autocomplete = "off";
    search.setAttribute("role", "combobox");
    search.setAttribute("aria-label", `Tìm ${labelText}`);
    search.setAttribute("aria-autocomplete", "list");
    search.setAttribute("aria-controls", listId);
    search.setAttribute("aria-expanded", "false");
    search.setAttribute("aria-haspopup", "listbox");
    search.required = select.required;
    search.disabled = select.disabled;
    select.required = false;

    const list = document.createElement("div");
    list.id = listId;
    list.className = "employee-autocomplete-suggestions";
    list.setAttribute("role", "listbox");
    list.hidden = true;
    wrapper.append(search, list);
    select.before(wrapper);
    select.hidden = true;

    if (explicitLabel) explicitLabel.htmlFor = searchId;
    const selected = select.selectedOptions[0];
    if (selected?.value) search.value = selectedLabel(selected);
    search.setCustomValidity(selected?.value || !search.required ? "" : `Chọn ${labelText} trong danh sách gợi ý.`);

    select.addEventListener("change", () => {
      const chosen = select.selectedOptions[0];
      search.value = chosen?.value ? selectedLabel(chosen) : "";
      search.setCustomValidity(chosen?.value || !search.required ? "" : `Chọn ${labelText} trong danh sách gợi ý.`);
      closeSuggestions(search, list);
    });
  }

  function closeSuggestions(search, list) {
    list.hidden = true;
    search.setAttribute("aria-expanded", "false");
    search.removeAttribute("aria-activedescendant");
  }

  function positionSuggestions(search, list) {
    if (list.hidden) return;
    const rect = search.getBoundingClientRect();
    const maxHeight = Math.min(260, window.innerHeight * 0.4);
    const below = window.innerHeight - rect.bottom;
    const placeAbove = below < Math.min(180, maxHeight) && rect.top > below;
    list.style.left = `${Math.max(8, rect.left)}px`;
    list.style.width = `${Math.min(rect.width, window.innerWidth - Math.max(8, rect.left) - 8)}px`;
    list.style.maxHeight = `${maxHeight}px`;
    list.style.top = placeAbove
      ? `${Math.max(8, rect.top - Math.min(maxHeight, list.scrollHeight) - 4)}px`
      : `${Math.min(window.innerHeight - 8, rect.bottom + 4)}px`;
  }

  function chooseOption(search, option) {
    const wrapper = search.closest(".employee-autocomplete");
    const list = wrapper.querySelector("[role=listbox]");
    const select = wrapper.nextElementSibling;
    select.value = option.value;
    search.value = selectedLabel(option);
    search.setCustomValidity("");
    select.dispatchEvent(new Event("change", { bubbles: true }));
    search.focus();
    closeSuggestions(search, list);
  }

  function renderSuggestions(search) {
    const wrapper = search.closest(".employee-autocomplete");
    const select = wrapper?.nextElementSibling;
    const list = wrapper?.querySelector("[role=listbox]");
    if (!select || !list) return;

    const query = normalize(search.value);
    const matches = [...select.options]
      .filter((option) => option.value && !option.disabled)
      .filter((option) => normalize(option.dataset.searchText || optionLabel(option)).includes(query))
      .slice(0, 8);
    list.replaceChildren();

    if (!matches.length) {
      const empty = document.createElement("div");
      empty.className = "employee-autocomplete-empty";
      const labelText = select.dataset.autocompleteLabel || "mục";
      empty.textContent = `Không tìm thấy ${labelText.toLocaleLowerCase("vi")} phù hợp.`;
      list.append(empty);
    } else {
      matches.forEach((option, index) => {
        const item = document.createElement("div");
        item.id = `${list.id}-option-${index}`;
        item.className = "employee-autocomplete-option";
        item.setAttribute("role", "option");
        item.setAttribute("aria-selected", "false");
        item.tabIndex = -1;
        item.dataset.employeeId = option.value;

        const name = document.createElement("span");
        name.textContent = optionLabel(option);
        item.append(name);
        const employeeType = typeLabels[option.dataset.employeeType];
        if (employeeType) {
          const type = document.createElement("small");
          type.textContent = employeeType;
          item.append(type);
        }
        list.append(item);
      });
    }

    list.hidden = false;
    search.setAttribute("aria-expanded", "true");
    positionSuggestions(search, list);
  }

  document.addEventListener("focusin", (event) => {
    const search = event.target.closest(".employee-autocomplete-input");
    if (search) renderSuggestions(search);
  });

  document.addEventListener("focusout", (event) => {
    const wrapper = event.target.closest(".employee-autocomplete");
    if (!wrapper || wrapper.contains(event.relatedTarget)) return;
    const search = wrapper.querySelector(".employee-autocomplete-input");
    const list = wrapper.querySelector("[role=listbox]");
    if (list) closeSuggestions(search, list);
  });

  document.addEventListener("input", (event) => {
    const search = event.target.closest(".employee-autocomplete-input");
    if (!search) return;
    const select = search.closest(".employee-autocomplete")?.nextElementSibling;
    if (select) {
      select.value = "";
      const labelText = select.dataset.autocompleteLabel || "mục";
      search.setCustomValidity(search.required ? `Chọn ${labelText} trong danh sách gợi ý.` : "");
    }
    renderSuggestions(search);
  });

  document.addEventListener("click", (event) => {
    const option = event.target.closest(".employee-autocomplete-option");
    if (option) {
      const search = option.closest(".employee-autocomplete")?.querySelector(".employee-autocomplete-input");
      const select = option.closest(".employee-autocomplete")?.nextElementSibling;
      const match = [...(select?.options || [])].find(
        (candidate) => candidate.value === option.dataset.employeeId,
      );
      if (search && match) chooseOption(search, match);
      return;
    }

    const search = event.target.closest(".employee-autocomplete-input");
    if (search) return;
    document.querySelectorAll(".employee-autocomplete-input").forEach((input) => {
      const list = input.closest(".employee-autocomplete")?.querySelector("[role=listbox]");
      if (list) closeSuggestions(input, list);
    });
  });

  document.addEventListener("keydown", (event) => {
    const search = event.target.closest(".employee-autocomplete-input");
    if (search && event.key === "Enter") {
      const select = search.closest(".employee-autocomplete")?.nextElementSibling;
      const query = normalize(search.value.trim());
      const exact = [...(select?.options || [])].find((candidate) => {
        if (!candidate.value || candidate.disabled) return false;
        const terms = normalize(candidate.dataset.searchText || optionLabel(candidate)).split(/\s+/);
        return terms[0] === query || normalize(optionLabel(candidate)) === query;
      });
      if (exact) {
        event.preventDefault();
        chooseOption(search, exact);
      }
      return;
    }
    if (search && event.key === "ArrowDown") {
      const firstOption = search.closest(".employee-autocomplete")?.querySelector(".employee-autocomplete-option");
      if (firstOption) {
        event.preventDefault();
        firstOption.focus();
      }
      return;
    }
    if (search && event.key === "Escape") {
      const list = search.closest(".employee-autocomplete")?.querySelector("[role=listbox]");
      if (list) closeSuggestions(search, list);
      return;
    }

    const option = event.target.closest(".employee-autocomplete-option");
    if (!option) return;
    const searchInput = option.closest(".employee-autocomplete")?.querySelector(".employee-autocomplete-input");
    const options = [...(option.parentElement?.querySelectorAll(".employee-autocomplete-option") || [])];
    const currentIndex = options.indexOf(option);
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const direction = event.key === "ArrowDown" ? 1 : -1;
      options[(currentIndex + direction + options.length) % options.length]?.focus();
    } else if (event.key === "Enter") {
      event.preventDefault();
      option.click();
    } else if (event.key === "Escape" && searchInput) {
      searchInput.focus();
      closeSuggestions(searchInput, option.parentElement);
    }
  });

  const repositionOpenLists = () => {
    document.querySelectorAll(".employee-autocomplete-input[aria-expanded=true]").forEach((search) => {
      const list = search.closest(".employee-autocomplete")?.querySelector("[role=listbox]");
      if (list) positionSuggestions(search, list);
    });
  };
  window.addEventListener("resize", repositionOpenLists);
  window.addEventListener("scroll", repositionOpenLists, true);

  function initializeAll(root = document) {
    const selector = "select[data-employee-autocomplete], select[data-searchable-select]";
    if (root.matches?.(selector)) initialize(root);
    root.querySelectorAll?.(selector).forEach(initialize);
  }

  initializeAll();
  new MutationObserver((records) => {
    records.forEach((record) => record.addedNodes.forEach((node) => {
      if (node.nodeType === Node.ELEMENT_NODE) initializeAll(node);
    }));
  }).observe(document.body, { childList: true, subtree: true });
})();
