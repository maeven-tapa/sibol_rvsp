(() => {
  const clock = document.getElementById('system-clock');
  if (!clock) return;
  const initial = Date.parse(clock.dataset.serverTime), started = performance.now();
  const formatter = new Intl.DateTimeFormat('en-PH', {timeZone:'Asia/Manila', year:'numeric', month:'short', day:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit', hour12:true});
  function tick() {
    const now = new Date(initial + performance.now() - started);
    clock.dateTime = now.toISOString(); clock.textContent = formatter.format(now);
  }
  tick(); setInterval(tick, 1000);
})();
