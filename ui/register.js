(async function () {
  const form = document.getElementById("register-form");
  const errorBox = document.getElementById("register-error");
  const doneBox = document.getElementById("register-done");
  const projectSelect = document.getElementById("reg-project");

  try {
    const names = await api("/api/projects/names");
    projectSelect.innerHTML = `<option value="">— не выбран —</option>` +
      names.map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join("");
  } catch {
    // список проектов не критичен для отправки заявки — остаётся только "не выбран"
  }

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    errorBox.hidden = true;
    const submitBtn = form.querySelector('button[type="submit"]');
    submitBtn.disabled = true;
    try {
      await api("/api/auth/register", {
        method: "POST",
        json: {
          login: document.getElementById("reg-login").value.trim(),
          password: document.getElementById("reg-password").value,
          full_name: document.getElementById("reg-full-name").value.trim(),
          position: document.getElementById("reg-position").value.trim(),
          project: projectSelect.value || null,
        },
      });
      form.hidden = true;
      doneBox.hidden = false;
    } catch (err) {
      errorBox.textContent = err.message;
      errorBox.hidden = false;
    } finally {
      submitBtn.disabled = false;
    }
  });
})();
