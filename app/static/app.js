document.querySelectorAll('[data-auto-submit]').forEach((input) => {
  input.addEventListener('change', () => input.form.requestSubmit());
});

const hoursInput = document.querySelector('#entry-hours');
if (hoursInput) {
  const setHours = (amount) => {
    hoursInput.value = Math.max(0.5, Math.min(24, amount));
    hoursInput.dispatchEvent(new Event('input'));
  };
  document.querySelectorAll('[data-hours-step]').forEach((button) => {
    button.addEventListener('click', () => setHours((Number(hoursInput.value) || 0) + Number(button.dataset.hoursStep)));
  });
  document.querySelectorAll('[data-hours]').forEach((button) => {
    button.addEventListener('click', () => setHours(Number(button.dataset.hours)));
  });
  const highlight = () => document.querySelectorAll('[data-hours]').forEach((button) => {
    button.setAttribute('aria-pressed', String(Number(button.dataset.hours) === Number(hoursInput.value)));
  });
  hoursInput.addEventListener('input', highlight);
  highlight();
}

// The server also prevents duplicate days and rejects stale edits.
document.querySelectorAll('form[method="post"]').forEach((form) => {
  form.addEventListener('submit', (event) => {
    if (form.dataset.submitting) {
      event.preventDefault();
      return;
    }
    form.dataset.submitting = 'true';
    form.setAttribute('aria-busy', 'true');
  });
});
window.addEventListener('pageshow', () => {
  document.querySelectorAll('form[data-submitting]').forEach((form) => {
    delete form.dataset.submitting;
    form.removeAttribute('aria-busy');
  });
});
