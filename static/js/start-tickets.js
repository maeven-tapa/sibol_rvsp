(() => {
  const form = document.getElementById('start-tickets-form');
  const field = form.elements.payment_qr;
  const preview = document.getElementById('payment-qr-preview');
  let previewUrl;
  function syncMode() {
    const selling = form.elements.ticket_workflow.value === 'selling';
    document.getElementById('payment-qr-fields').hidden = !selling;
    field.required = selling;
    field.disabled = !selling;
  }
  form.querySelectorAll('[name=ticket_workflow]').forEach(input => input.addEventListener('change', syncMode));
  field.addEventListener('change', () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    const file = field.files[0];
    preview.hidden = !file;
    if (file) { previewUrl = URL.createObjectURL(file); preview.src = previewUrl; }
    else preview.removeAttribute('src');
  });
  syncMode();
})();
