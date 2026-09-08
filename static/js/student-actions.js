(() => {
  const edit = document.getElementById('studentEditModal');
  edit?.addEventListener('show.bs.modal', event => {
    const button = event.relatedTarget;
    if (!button) return; // Keep submitted values when validation reopens the panel.
    const form = edit.querySelector('form');
    form.querySelectorAll('.errorlist').forEach(error => error.remove());
    form.elements.student_id.value = button.dataset.studentId;
    for (const [field, key] of Object.entries({tupc_id: 'tupcId', name: 'name', course: 'course', section: 'section'})) {
      form.elements[`edit-${field}`].value = button.dataset[key];
    }
  });
  const status = document.getElementById('studentStatusModal');
  status?.addEventListener('show.bs.modal', event => {
    const button = event.relatedTarget;
    if (!button) return;
    const disable = button.dataset.active === 'true';
    const verb = disable ? 'Disable' : 'Enable';
    const form = status.querySelector('form');
    form.elements.student_id.value = button.dataset.studentId;
    form.elements.action.value = disable ? 'student_disable' : 'student_enable';
    status.querySelector('.modal-title').textContent = `${verb} student`;
    status.querySelector('[data-student-prompt]').textContent = `${verb} ${button.dataset.name}?`;
    status.querySelector('[data-status-description]').textContent = disable
      ? 'The student will be unable to register or sign in. Their details and existing tickets will be retained.'
      : 'The student will be able to register or sign in again.';
    status.querySelector('[data-status-submit]').textContent = `${verb} student`;
  });
  const remove = document.getElementById('studentDeleteModal');
  remove?.addEventListener('show.bs.modal', event => {
    const button = event.relatedTarget;
    if (!button) return;
    remove.querySelector('form').elements.student_id.value = button.dataset.studentId;
    remove.querySelector('[data-student-prompt]').textContent = `Delete ${button.dataset.name}?`;
  });
})();
