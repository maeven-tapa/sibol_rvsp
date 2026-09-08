(() => {
  const root = document.documentElement;
  const key = 'sibol-auth-transition';
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  let navigating = false;
  let incoming = false;
  let portalTransition = false;
  let adminTransition = false;
  try {
    const saved = JSON.parse(sessionStorage.getItem(key) || 'null');
    sessionStorage.removeItem(key);
    incoming = saved && saved.path === location.pathname && Date.now() - saved.at < 15000;
    portalTransition = Boolean(incoming && saved.portal);
    adminTransition = Boolean(incoming && saved.admin);
  } catch (_) {}
  if (incoming) root.classList.add('page-is-transitioning');
  if (portalTransition) root.classList.add('page-transition-portal');
  if (adminTransition) root.classList.add('page-transition-admin');
  function show(active, portal = portalTransition) {
    root.classList.toggle('page-transition-portal', portal);
    root.classList.toggle('page-transition-admin', adminTransition);
    root.classList.toggle('page-is-transitioning', active);
    document.querySelector('.page-transition')?.setAttribute('aria-hidden', String(!active));
  }
  document.addEventListener('DOMContentLoaded', () => {
    const loader = document.querySelector('.page-transition');
    if (loader && !loader.querySelector('.transition-logo')) {
      const logo = document.createElement('img');
      logo.className = 'transition-logo';
      logo.src = '/static/images/tupsibol_logo.png';
      logo.alt = 'TUP Sibol';
      loader.prepend(logo);
    }
    if (incoming) {
      show(true);
      requestAnimationFrame(() => setTimeout(() => show(false), reduced ? 0 : 180));
    }
    document.querySelector('[data-admin-login]')?.addEventListener('submit', () => {
      adminTransition = true;
      show(true);
      try { sessionStorage.setItem(key, JSON.stringify({path: '/dashboard/', at: Date.now(), admin: true})); } catch (_) {}
    });
    document.addEventListener('click', event => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const link = event.target.closest('a[href]');
      if (!link || link.hasAttribute('download') || (link.target && link.target !== '_self')) return;
      const url = new URL(link.href);
      const fromHome = document.querySelector('.home-photo');
      const fromAuth = document.body.classList.contains('auth-page-theme');
      const fromTickets = document.body.classList.contains('tickets-page');
      const signsOut = url.pathname === '/logout/';
      const opensAuth = fromHome && ['/login/', '/register/'].includes(url.pathname);
      const returnsHome = (fromAuth && link.classList.contains('auth-home-brand') || fromTickets) && url.pathname === '/';
      const opensPortal = ['/tickets/', '/dashboard/'].includes(url.pathname);
      if (url.origin !== location.origin || (!opensAuth && !returnsHome && !opensPortal && !signsOut)) return;
      event.preventDefault();
      if (navigating) return;
      navigating = true;
      adminTransition = url.pathname === '/dashboard/';
      try { sessionStorage.setItem(key, JSON.stringify({path: signsOut ? '/' : url.pathname, at: Date.now(), portal: opensPortal, admin: adminTransition})); } catch (_) {}
      show(true, opensPortal);
      setTimeout(() => location.assign(url.href), reduced ? 0 : 320);
      setTimeout(() => { navigating = false; show(false); }, 12000);
    });
  });
  window.addEventListener('pageshow', event => {
    if (event.persisted) { navigating = false; show(false); }
  });
})();
