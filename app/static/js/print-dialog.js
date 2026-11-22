(() => {
  const container = document.getElementById("print-container");
  const status = document.getElementById("print-status");
  const retry = document.getElementById("print-retry");
  if (!container || !status || !retry) {
    const preview = document.querySelector(".rendered-document");
    const previewButton = document.getElementById("print-document-button");
    if (!preview || !previewButton) return;
    previewButton.addEventListener("click", async () => {
      const images = [...preview.querySelectorAll(".print-page")];
      await Promise.all(images.map((image) => image.decode().catch(() => undefined)));
      window.print();
    });
    return;
  }

  let busy = false;
  let activeButton = null;

  const cleanup = () => {
    document.body.classList.remove("printing-document");
    container.hidden = true;
    container.replaceChildren();
    container.setAttribute("aria-hidden", "true");
    retry.hidden = true;
    if (activeButton) activeButton.disabled = false;
    activeButton = null;
    busy = false;
    status.textContent = "Đã đóng hộp thoại In.";
    const queue = document.getElementById("queue-fragment");
    if (window.htmx && queue) window.htmx.trigger(queue, "refreshQueue");
  };

  const startPrint = () => {
    if (container.hidden) return;
    retry.hidden = false;
    status.textContent = "Hộp thoại In chưa hiện? Bấm ‘In lại biểu’.";
    window.print();
  };

  const printFromUrl = async (url, button) => {
    if (busy) return;
    const target = new URL(url, window.location.href);
    if (target.origin !== window.location.origin) return;

    busy = true;
    activeButton = button;
    button.disabled = true;
    retry.hidden = true;
    status.hidden = false;
    status.textContent = "Đang chuẩn bị biểu in…";

    try {
      const response = await fetch(target, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          Accept: "text/html",
          "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        },
        body: new URLSearchParams({ csrf_token: button.dataset.csrfToken || "" }),
      });
      if (!response.ok) {
        const message = (await response.text()).trim();
        throw new Error(message || "Không tạo được biểu in.");
      }
      const html = await response.text();
      const documentCopy = new DOMParser().parseFromString(html, "text/html");
      const pages = [...documentCopy.querySelectorAll(".print-page")];
      if (!pages.length) throw new Error("Biểu in không có trang nào.");

      const pageImages = pages.map((source) => {
        const image = new Image();
        image.className = "print-page";
        image.alt = source.alt;
        image.src = source.src;
        return image;
      });
      container.replaceChildren(...pageImages);
      await Promise.all(pageImages.map((image) => image.decode()));

      container.hidden = false;
      container.setAttribute("aria-hidden", "false");
      document.body.classList.add("printing-document");
      window.addEventListener("afterprint", cleanup, { once: true });
      startPrint();
    } catch (error) {
      container.hidden = true;
      container.replaceChildren();
      button.disabled = false;
      activeButton = null;
      busy = false;
      status.textContent = error instanceof Error ? error.message : "Không tạo được biểu in.";
    }
  };

  const printHtmlBatch = async (url, button) => {
    if (busy) return;
    const form = button.closest("form");
    if (!form || !form.querySelectorAll('input[name="lot_id"]:checked').length) {
      status.hidden = false;
      status.textContent = "Chọn ít nhất một lô để in.";
      return;
    }
    const target = new URL(url, window.location.href);
    if (target.origin !== window.location.origin) return;
    busy = true;
    activeButton = button;
    button.disabled = true;
    retry.hidden = true;
    status.hidden = false;
    status.textContent = "Đang chuẩn bị biểu QC theo lô…";
    try {
      const response = await fetch(target, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          Accept: "text/html",
          "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        },
        body: new URLSearchParams(new FormData(form)),
      });
      if (!response.ok) throw new Error((await response.text()).trim() || "Không tạo được biểu.");
      const parsed = new DOMParser().parseFromString(await response.text(), "text/html");
      const pages = [...parsed.querySelectorAll(".lot-print-page")];
      if (!pages.length) throw new Error("Không có biểu nào được tạo.");
      const copies = pages.map((page) => page.cloneNode(true));
      container.replaceChildren(...copies);
      await Promise.all(copies.flatMap((page) => [...page.querySelectorAll("img")].map((image) => image.decode().catch(() => undefined))));
      container.hidden = false;
      container.setAttribute("aria-hidden", "false");
      document.body.classList.add("printing-document");
      window.addEventListener("afterprint", cleanup, { once: true });
      startPrint();
    } catch (error) {
      container.hidden = true;
      container.replaceChildren();
      button.disabled = false;
      activeButton = null;
      busy = false;
      status.textContent = error instanceof Error ? error.message : "Không tạo được biểu.";
    }
  };

  document.addEventListener("click", (event) => {
    const selectLots = event.target.closest("[data-select-lots]");
    if (selectLots) {
      const form = selectLots.closest("form");
      const boxes = [...form.querySelectorAll('input[name="lot_id"]')];
      const allChecked = boxes.length > 0 && boxes.every((box) => box.checked);
      boxes.forEach((box) => { box.checked = !allChecked; });
      selectLots.textContent = allChecked ? "Chọn lô hiển thị" : "Bỏ chọn lô";
      return;
    }
    const htmlPrintButton = event.target.closest("[data-html-print-url]");
    if (htmlPrintButton) {
      event.preventDefault();
      printHtmlBatch(htmlPrintButton.dataset.htmlPrintUrl, htmlPrintButton);
      return;
    }
    const button = event.target.closest("[data-print-url]");
    if (!button) return;
    event.preventDefault();
    printFromUrl(button.dataset.printUrl, button);
  });

  retry.addEventListener("click", startPrint);
})();
