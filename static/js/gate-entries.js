(() => {
  const body = document.getElementById('entry-log-body'), status = document.getElementById('entry-log-status');
  let timer;
  const scanners = new Set();
  const settingsUrl = document.querySelector('[data-gate-settings]').dataset.gateSettings;
  window.addEventListener('message', event => {
    if (event.origin === window.location.origin && event.data?.type === 'sibol-scanner-open' && event.source && event.source !== window) scanners.add(event.source);
  });
  document.getElementById('open-scanner').addEventListener('click', event => {
    event.preventDefault();
    const scanner = window.open(event.currentTarget.href, '_blank');
    if (scanner) scanners.add(scanner);
    else status.textContent = 'Allow pop-ups to open the scanning station.';
  });
  function checkScanners() {
    if (!scanners.size) return;
    for (const scanner of scanners) if (scanner.closed) scanners.delete(scanner);
    if (!scanners.size) window.location.replace(settingsUrl);
  }
  const scannerWatch = setInterval(checkScanners, 500);
  window.addEventListener('focus', checkScanners);
  async function refresh() {
    try {
      const response = await fetch('?format=json', {cache:'no-store'});
      if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new Error('Unable to load entries. Check your connection and sign-in.');
      const data = await response.json();
      body.replaceChildren();
      data.entries.forEach(entry => { const row = document.createElement('tr'); ['time','name','code','type','relay','direction','status','operator'].forEach(key => {const cell = document.createElement('td'); cell.textContent = entry[key]; row.append(cell);}); body.append(row); });
      status.textContent = data.entries.length ? `Updated ${new Date().toLocaleTimeString()}` : 'No entries yet. Admissions will appear here when a pass is scanned in gate-entry mode.';
    } catch (error) { status.textContent = error.message; }
    timer = setTimeout(refresh, 3000);
  }
  refresh();
  window.addEventListener('pagehide', () => { clearTimeout(timer); clearInterval(scannerWatch); });
})();
