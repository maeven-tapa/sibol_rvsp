(() => {
  const url = document.currentScript.dataset.adminUrl;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  let opening = false;
  document.querySelectorAll('.site-brand, .auth-home-brand').forEach(logo => {
    let timer, held = false;
    const cancel = () => { clearTimeout(timer); timer = null; };
    const openAdmin = async () => {
      if (opening) return;
      opening = held = true;
      const emblem = logo.querySelector('img') || logo;
      if (!reduced) {
        const rotation = emblem.animate([{transform: 'rotate(0deg)'}, {transform: 'rotate(360deg)'}], {duration: 700, easing: 'ease-in-out'});
        await rotation.finished.catch(() => {});
      }
      document.documentElement.classList.add('page-transition-admin', 'page-is-transitioning');
      document.querySelector('.page-transition')?.setAttribute('aria-hidden', 'false');
      try { sessionStorage.setItem('sibol-auth-transition', JSON.stringify({path: new URL(url, location.href).pathname, at: Date.now(), admin: true})); } catch (_) {}
      setTimeout(() => location.assign(url), reduced ? 0 : 650);
    };
    const start = () => { if (opening) return; cancel(); held = false; timer = setTimeout(openAdmin, 2000); };
    logo.addEventListener('pointerdown', event => { if (event.button === 0) start(); });
    ['pointerup', 'pointercancel', 'pointerleave', 'blur'].forEach(type => logo.addEventListener(type, cancel));
    logo.addEventListener('keydown', event => { if (['Enter', ' '].includes(event.key) && !event.repeat) { event.preventDefault(); start(); } });
    logo.addEventListener('keyup', event => { if (['Enter', ' '].includes(event.key)) { event.preventDefault(); cancel(); if (!held && !opening) location.assign(logo.href); } });
    logo.addEventListener('click', event => { if (held || opening) { event.preventDefault(); event.stopPropagation(); } });
    logo.addEventListener('contextmenu', event => event.preventDefault());
    logo.addEventListener('dragstart', event => event.preventDefault());
    logo.style.touchAction = 'manipulation';
    logo.style.userSelect = 'none';
    window.addEventListener('pageshow', event => { if (event.persisted) { cancel(); held = opening = false; document.documentElement.classList.remove('page-transition-admin'); } });
  });
})();

document.addEventListener('DOMContentLoaded', () => {
  const modal = document.getElementById('programItemModal');
  const dialog = modal?.querySelector('.modal-dialog');
  const handle = modal?.querySelector('.modal-header');
  if (!dialog || !handle) return;
  let startX, startY, initialX, initialY;
  handle.addEventListener('pointerdown', event => {
    if (event.target.closest('button, input, select, textarea')) return;
    const box = dialog.getBoundingClientRect();
    startX = event.clientX; startY = event.clientY; initialX = box.left; initialY = box.top;
    dialog.style.position = 'fixed'; dialog.style.margin = '0'; dialog.style.left = `${initialX}px`; dialog.style.top = `${initialY}px`;
    handle.setPointerCapture(event.pointerId);
  });
  handle.addEventListener('pointermove', event => {
    if (startX === undefined) return;
    dialog.style.left = `${initialX + event.clientX - startX}px`;
    dialog.style.top = `${initialY + event.clientY - startY}px`;
  });
  handle.addEventListener('pointerup', () => { startX = undefined; });
});
