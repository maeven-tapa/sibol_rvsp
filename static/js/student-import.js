// Preview muna ang CSV bago i-enable ang Add students button.
(() => {
  const form = document.getElementById('student-import-form');
  if (!form) return;
  const file = document.getElementById('student-import-file');
  const add = document.getElementById('student-import-add');
  const status = document.getElementById('student-import-status');
  const preview = document.getElementById('student-import-preview');
  let generation = 0;
  async function submit(action) {
    const current = ++generation;
    add.disabled = true;
    preview.hidden = true;
    preview.querySelector('tbody').replaceChildren();
    status.replaceChildren();
    if (!file.files.length) return;
    file.disabled = true;
    status.textContent = action === 'add' ? 'Adding students…' : 'Validating CSV…';
    const body = new FormData(form);
    // Hindi kasama sa FormData ang disabled input, kaya ilagay nang manual ang file.
    body.set('file', file.files[0]);
    body.set('action', action);
    try {
      const response = await fetch(form.action, {method: 'POST', body});
      if (response.redirected) throw new Error('Your session has expired. Reload and sign in again.');
      const data = await response.json();
      // Ignore ang lumang response kung may mas bagong request na.
      if (current !== generation) return;
      if (data.added) {
        status.textContent = `${data.added} students added.`;
        window.location.reload();
        return;
      }
      status.replaceChildren();
      for (const error of data.errors || []) {
        const line = document.createElement('p');
        line.className = 'text-danger mb-1';
        line.textContent = error;
        status.append(line);
      }
      for (const values of data.rows || []) {
        const row = document.createElement('tr');
        for (const value of values) {
          const cell = document.createElement('td');
          // Plain text lang ang CSV values para hindi ma-render bilang HTML.
          cell.textContent = value;
          row.append(cell);
        }
        preview.querySelector('tbody').append(row);
      }
      preview.hidden = !data.rows?.length;
      if (response.ok && !data.errors?.length && data.rows?.length) {
        status.textContent = `${data.rows.length} students ready to add.`;
        add.textContent = `Add ${data.rows.length} students`;
        add.disabled = false;
      }
    } catch (error) {
      status.textContent = error.message === 'Your session has expired. Reload and sign in again.'
        ? error.message : 'Import could not be confirmed. Reload the roster before retrying.';
    } finally {
      file.disabled = false;
    }
  }
  file.addEventListener('change', () => submit('preview'));
  add.addEventListener('click', () => submit('add'));
})();
