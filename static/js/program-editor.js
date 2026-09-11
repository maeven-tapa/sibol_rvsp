(() => {
  const modal = document.getElementById('programItemModal');
  if (!modal) return;
  const form = document.getElementById('program-entry-form');
  const list = document.getElementById('program-draft-list');
  const add = document.getElementById('program-add');
  const save = document.getElementById('program-save');
  const error = document.getElementById('program-editor-error');
  const fields = ['item_type', 'title', 'description', 'speaker', 'hymn_language'];
  // Basahin ang saved program mula sa template; hiwalay ang editable items sa browser.
  const original = JSON.parse(document.getElementById('program-editor-data').textContent);
  let items = [], editing = null, dragging = null, saving = false;
  const speaker = value => /^(na|n\/a)$/i.test(value.trim()) ? '' : value.trim();
  function clear() { form.reset(); editing = null; add.textContent = 'Add item'; }
  function announce(text) { document.getElementById('program-editor-status').textContent = text; }
  function edit(index) {
    editing = index;
    fields.forEach(field => { form.elements[field].value = items[index][field] || ''; });
    add.textContent = 'Update item';
    form.elements.title.focus();
  }
  // Baguhin ang order ng draft items at i-check muna kung valid ang target index.
  function move(from, to) {
    if (from === to || to < 0 || to >= items.length) return;
    const selected = editing === null ? null : items[editing];
    items.splice(to, 0, items.splice(from, 1)[0]);
    if (selected) editing = items.indexOf(selected);
    render(); announce('Program order updated.');
  }
  function render() {
    list.replaceChildren();
    document.getElementById('program-empty').hidden = items.length > 0;
    items.forEach((item, index) => {
      const row = document.createElement('li'); row.className = 'program-draft-row'; row.draggable = true;
      const handle = document.createElement('span'); handle.className = 'drag-handle'; handle.textContent = '☰'; handle.setAttribute('aria-hidden', 'true');
      const copy = document.createElement('div'); copy.className = 'program-draft-copy';
      const title = document.createElement('b'); title.textContent = `${index + 1}. ${item.title}`;
      const type = document.createElement('small'); type.textContent = [...form.elements.item_type.options].find(option => option.value === item.item_type)?.textContent || item.item_type;
      copy.append(title, type);
      if (speaker(item.speaker || '')) { const name = document.createElement('small'); name.textContent = speaker(item.speaker); copy.append(name); }
      const actions = document.createElement('div'); actions.className = 'program-draft-actions';
      function button(text, label, run, disabled = false) { const b = document.createElement('button'); b.type = 'button'; b.textContent = text; b.setAttribute('aria-label', `${label} ${item.title}`); b.disabled = disabled; b.addEventListener('click', run); actions.append(b); }
      button('↑', 'Move up', () => move(index, index - 1), index === 0);
      button('↓', 'Move down', () => move(index, index + 1), index === items.length - 1);
      button('Edit', 'Edit', () => edit(index));
      button('×', 'Remove', () => { items.splice(index, 1); if (editing === index) clear(); else if (editing > index) editing--; render(); });
      row.append(handle, copy, actions);
      row.addEventListener('dragstart', event => { dragging = index; event.dataTransfer.setData('text/plain', String(index)); event.dataTransfer.effectAllowed = 'move'; row.classList.add('dragging'); });
      row.addEventListener('dragover', event => { event.preventDefault(); row.classList.add('drag-over'); });
      row.addEventListener('dragleave', () => row.classList.remove('drag-over'));
      row.addEventListener('drop', event => { event.preventDefault(); if (dragging !== null) move(dragging, index); dragging = null; });
      row.addEventListener('dragend', () => { dragging = null; list.querySelectorAll('li').forEach(el => el.classList.remove('dragging', 'drag-over')); });
      list.append(row);
    });
  }
  modal.addEventListener('show.bs.modal', event => {
    items = original.map(item => ({...item, speaker: speaker(item.speaker || '')}));
    clear(); error.hidden = true; render();
    const id = Number(event.relatedTarget?.dataset.id);
    const index = items.findIndex(item => item.id === id);
    if (index >= 0) edit(index);
  });
  modal.addEventListener('hide.bs.modal', event => { if (saving) event.preventDefault(); });
  form.addEventListener('submit', event => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    const item = Object.fromEntries(fields.map(field => [field, form.elements[field].value.trim()]));
    if (!item.title) { form.elements.title.focus(); return; }
    item.speaker = speaker(item.speaker);
    if (editing === null) items.push(item); else items[editing] = {...items[editing], ...item};
    clear(); render(); error.hidden = true; announce('Item added to the program list.'); form.elements.item_type.focus();
  });
  document.getElementById('program-clear').addEventListener('click', clear);
  save.addEventListener('click', async () => {
    if (saving) return;
    if (fields.some(field => form.elements[field].value.trim())) { error.textContent = 'Click Add item or Update item to include the inputs, or Clear inputs before saving.'; error.hidden = false; return; }
    saving = true; save.disabled = true; error.hidden = true;
    form.inert = true; list.inert = true;
    try {
      const body = new FormData(); body.set('action', 'program_flow_save'); body.set('items', JSON.stringify(items)); body.set('csrfmiddlewaretoken', form.elements.csrfmiddlewaretoken.value);
      const response = await fetch(window.location.pathname, {method: 'POST', body});
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.error || 'Unable to save the program. Please try again.');
      window.location.reload();
    } catch (failure) { error.textContent = failure.message || 'Unable to save the program. Please try again.'; error.hidden = false; }
    finally { saving = false; save.disabled = false; form.inert = false; list.inert = false; }
  });
})();
