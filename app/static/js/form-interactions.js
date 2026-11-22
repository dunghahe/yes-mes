(() => {
  const focusable = 'button:not([disabled]), input:not([type="hidden"]):not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex="0"]';
  const visibleControls = (root) => [...root.querySelectorAll(focusable)]
    .filter((node) => node.getClientRects().length && !node.closest('[hidden]'));
  const openModal = () => [...document.querySelectorAll('.modal-backdrop [role="dialog"]')]
    .filter((node) => node.getClientRects().length).at(-1);
  let activeModal = null;
  let returnFocus = null;
  const syncModal = () => {
    const modal = openModal();
    if (modal === activeModal) return;
    if (modal) {
      returnFocus = document.activeElement;
      activeModal = modal;
      visibleControls(modal)[0]?.focus();
    } else {
      activeModal = null;
      if (returnFocus?.isConnected) returnFocus.focus();
      returnFocus = null;
    }
  };
  new MutationObserver(syncModal).observe(document.body, {
    subtree: true, attributes: true, attributeFilter: ['style', 'hidden'],
  });
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Tab') return;
    const modal = openModal();
    if (!modal) return;
    const controls = visibleControls(modal);
    const first = controls[0];
    const last = controls.at(-1);
    if (!first) return;
    if (!modal.contains(document.activeElement)) {
      event.preventDefault();
      (event.shiftKey ? last : first).focus();
    } else if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });

  const pending = new WeakSet();
  const unlock = (form) => {
    pending.delete(form);
    form.querySelectorAll('[data-submit-busy]').forEach((button) => {
      button.disabled = false;
      button.removeAttribute('data-submit-busy');
      button.removeAttribute('aria-busy');
    });
  };
  document.addEventListener('submit', (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || form.method.toLowerCase() !== 'post') return;
    if (pending.has(form)) {
      event.preventDefault();
      return;
    }
    // Run after payload builders and native/HTMX submission handlers.
    setTimeout(() => {
      if (event.defaultPrevented && !form.hasAttribute('hx-post')) return;
      pending.add(form);
      form.querySelectorAll('button[type="submit"]:not([disabled])').forEach((button) => {
        button.disabled = true;
        button.dataset.submitBusy = 'true';
        button.setAttribute('aria-busy', 'true');
      });
    }, 0);
  });
  document.addEventListener('htmx:afterRequest', (event) => {
    const form = event.detail.elt?.closest('form');
    if (form) unlock(form);
  });
  window.addEventListener('pageshow', () => document.querySelectorAll('form').forEach(unlock));
  syncModal();
})();
