(() => {
  const form = document.getElementById('registration-form');
  const steps = [...form.querySelectorAll('.registration-step')];
  const indicators = [...document.querySelectorAll('.registration-progress li')];
  let current = 0;
  const page = document.querySelector('.registration-page');
  const card = document.querySelector('.registration-card');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  let busy = false;
  let submitting = false;
  function setBusy(active) {
    busy = active;
    page.classList.toggle('registration-switching', active);
    card.setAttribute('aria-busy', String(active));
    card.inert = active;
  }
  const transitionPause = () => new Promise(resolve => setTimeout(resolve, reduced ? 0 : 650));
  const value = name => form.elements[name].value.trim();
  function show(index, focus = true) {
    current = index;
    steps.forEach((step, i) => { step.hidden = i !== index; });
    indicators.forEach((item, i) => {
      item.classList.toggle('complete', i < index);
      if (i === index) item.setAttribute('aria-current', 'step');
      else item.removeAttribute('aria-current');
    });
    if (index === 2) {
      form.querySelectorAll('[data-review]').forEach(el => {
        el.textContent = el.dataset.review === 'full_name' ? `${value('first_name')} ${value('last_name')}` : value(el.dataset.review);
      });
    }
    if (focus) {
      const heading = steps[index].querySelector('h1');
      heading.tabIndex = -1;
      heading.focus();
    }
  }
  function validate(index) {
    for (const input of steps[index].querySelectorAll('input')) {
      if (!input.checkValidity()) { show(index, false); input.reportValidity(); return false; }
    }
    return true;
  }
  form.elements.username.addEventListener('input', e => { e.target.value = e.target.value.toUpperCase(); });
  async function next() {
    if (busy) return;
    if (!validate(current)) return;
    if (current === 0) {
      const button = steps[0].querySelector('.registration-next');
      const error = document.getElementById('roster-error');
      if (button.disabled) return;
      button.disabled = true;
      error.hidden = true;
      setBusy(true);
      try {
        const pause = transitionPause();
        const response = await fetch(form.dataset.checkUrl, {method: 'POST', headers: {'X-CSRFToken': form.elements.csrfmiddlewaretoken.value}, body: new URLSearchParams({tupc_id: value('username')})});
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Unable to check this student ID.');
        form.elements.first_name.value = data.first_name;
        form.elements.last_name.value = data.last_name;
        document.getElementById('roster-details').textContent = `${data.course} · ${data.section}`;
        await pause;
        setBusy(false);
        show(1);
      } catch (e) { error.textContent = e.message || 'Please try again.'; error.hidden = false; }
      finally { setBusy(false); button.disabled = false; }
    } else show(current + 1);
  }
  form.querySelectorAll('.registration-next').forEach(button => button.addEventListener('click', next));
  form.querySelectorAll('.registration-back').forEach(button => button.addEventListener('click', async () => {
    if (busy) return;
    setBusy(true);
    await transitionPause();
    setBusy(false);
    show(current - 1);
  }));
  form.addEventListener('submit', async event => {
    if (submitting) return;
    event.preventDefault();
    if (busy) return;
    if (current < 1) { event.preventDefault(); next(); return; }
    if (!validate(0) || !validate(1)) return;
    setBusy(true);
    await transitionPause();
    submitting = true;
    form.requestSubmit();
  });
  window.addEventListener('pageshow', event => {
    if (event.persisted) { submitting = false; setBusy(false); }
  });
  const errorIndex = steps.findIndex(step => step.querySelector('.errorlist'));
  show(errorIndex < 0 ? 0 : errorIndex, false);
})();
