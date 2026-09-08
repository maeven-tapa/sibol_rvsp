const pages = document.querySelectorAll('.page');
function goTo(id) { pages.forEach(p => p.classList.toggle('active', p.id === id)); window.scrollTo(0,0); document.querySelectorAll('[data-page]').forEach(x => x.classList.toggle('active', x.dataset.page === id)); }
document.querySelectorAll('[data-page]').forEach(el => el.addEventListener('click', e => { e.preventDefault(); goTo(el.dataset.page); }));
document.querySelectorAll('.select-ticket').forEach(btn => btn.addEventListener('click', () => { document.querySelector('#selectedType').innerHTML = `${btn.dataset.type} <small>₱${btn.dataset.price}</small>`; goTo('register'); }));
document.querySelector('#registerForm').addEventListener('submit', e => { e.preventDefault(); goTo('tickets'); });
document.querySelector('#loginForm').addEventListener('submit', e => { e.preventDefault(); goTo('tickets'); });
document.querySelector('#showTicket').addEventListener('click', () => bootstrap.Modal.getOrCreateInstance(document.querySelector('#ticketModal')).show());
document.querySelectorAll('[data-admin]').forEach(btn => btn.addEventListener('click', () => {
  document.querySelectorAll('[data-admin]').forEach(x => x.classList.remove('active'));
  btn.classList.add('active');
  document.querySelector(`#${btn.dataset.admin}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}));
document.querySelectorAll('.gate-type').forEach(btn => btn.addEventListener('click', () => { document.querySelectorAll('.gate-type').forEach(b => b.classList.remove('active')); btn.classList.add('active'); document.querySelector('#gateLabel').textContent = `${btn.dataset.gate.toUpperCase()} GATE`; document.querySelector('.gate-count').innerHTML = btn.dataset.gate === 'VIP' ? '<b>284</b><span>VIP guests<br>checked in today</span>' : '<b>552</b><span>Regular guests<br>checked in today</span>'; }));
