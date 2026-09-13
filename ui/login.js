(async function () {
  // Уже залогинен — сразу на список проектов.
  try {
    await api("/api/me");
    window.location.href = "projects.html";
    return;
  } catch {
    // не залогинен — показываем форму как есть
  }

  const form = document.getElementById("login-form");
  const errorBox = document.getElementById("login-error");

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    errorBox.hidden = true;
    const login = document.getElementById("login").value.trim();
    const password = document.getElementById("password").value;
    const submitBtn = form.querySelector("button[type=submit]");
    submitBtn.disabled = true;
    try {
      await api("/api/login", { method: "POST", json: { login, password } });
      window.location.href = "projects.html";
    } catch (err) {
      errorBox.textContent = err.status === 401 ? "Неверный логин или пароль" : err.message;
      errorBox.hidden = false;
    } finally {
      submitBtn.disabled = false;
    }
  });
})();
