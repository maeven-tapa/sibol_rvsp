(() => {
  const form = document.getElementById('gate-setup-form');
  const mobile = form.dataset.mobile === 'true' || window.sibolMobileScanner;
  if (mobile) {
    form.elements.mobile.value = '1';
    form.querySelectorAll('[name=mode]').forEach(input => {
      const verify = input.value === 'verify';
      input.checked = verify;
      input.disabled = !verify;
      input.closest('label').hidden = !verify;
      if (verify) input.closest('label').querySelector('strong').textContent = 'Reservation check (Mobile)';
    });
    form.querySelector('.station-modes').style.gridTemplateColumns = '1fr';
  }
  function syncMode() {
    const usesRelay = form.elements.mode.value === 'entry';
    document.getElementById('usb-fields').hidden = !usesRelay;
    document.getElementById('relay-note').hidden = !usesRelay;
    form.elements.port.required = usesRelay;
    document.querySelectorAll('#usb-fields input, #usb-fields select, #usb-fields button').forEach(field => {
      field.disabled = !usesRelay;
    });
  }
  form.querySelectorAll('[name=mode]').forEach(input => input.addEventListener('change', syncMode));
  window.addEventListener('pageshow', syncMode);
  syncMode();
  const swap = document.getElementById('swap-relays');
  swap.addEventListener('click', () => {
    document.querySelectorAll('.relay-map > span').forEach(card => {
      card.classList.remove('relay-swapping');
      void card.offsetWidth;
      card.classList.add('relay-swapping');
      clearTimeout(card.swapTimer);
      card.swapTimer = setTimeout(() => card.classList.remove('relay-swapping'), 700);
    });
    const swapped = form.elements.swapped.value !== '1';
    form.elements.swapped.value = swapped ? '1' : '0';
    swap.setAttribute('aria-pressed', String(swapped));
    document.getElementById('gate-1-relay').textContent = swapped ? 'Relay 2' : 'Relay 1';
    document.getElementById('gate-2-relay').textContent = swapped ? 'Relay 1' : 'Relay 2';
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const error = document.getElementById('setup-error');
    error.hidden = true;
    const scanner = window.open('about:blank', '_blank');
    if (!scanner) { error.textContent = 'Allow pop-ups for this site to open the scanning station in a new tab.'; error.hidden = false; return; }
    if (scanner) scanner.document.title = 'Opening scanning station';
    if (scanner) scanner.document.body.textContent = 'Connecting the scanning station…';
    const button = form.querySelector('button:not([type="button"])');
    button.disabled = true;
    try {
      const response = await fetch(form.action || window.location.href, {method:'POST', headers:{Accept:'application/json'}, body:new FormData(form)});
      if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('Session expired. Sign in and try again.');
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Unable to open the station.');
      scanner.location.replace(result.scanner_url);
      window.location.assign(result.entry_url);
    } catch (failure) { scanner?.close(); error.textContent = failure.message; error.hidden = false; button.disabled = false; }
  });
})();
