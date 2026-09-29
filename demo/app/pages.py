"""HTML-страницы демо-магазина: логин, список каталога, карточка товара,
подтверждение заказа. Без шаблонизатора (в requirements.txt нет jinja2) —
простые f-строки с инлайн CSS/JS, цвета и отступы взяты из DESIGN.md
(тёмная тема, только эти токены, см. корень репозитория)."""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["pages"])

_CSS = """
:root {
  --bg: #0f1223; --surface: #1b2036; --border: #262c47;
  --text: #e7e9f5; --text-muted: #9298b8; --accent: #2563eb; --accent-hover: #1d4ed8;
  --danger: #ff4d6d;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font-family: "Golos Text", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  font-size: 14px; line-height: 1.45; padding: 28px;
}
h1 { font-size: 22px; font-weight: 700; margin: 0 0 16px; }
.card {
  background: var(--surface); border: 1px solid var(--border); border-radius: 16px;
  padding: 16px 18px; max-width: 420px; margin-bottom: 12px;
}
label { display: block; font-size: 11px; letter-spacing: .06em; text-transform: uppercase;
  font-weight: 600; color: var(--text-muted); margin-bottom: 4px; }
input {
  width: 100%; background: #232945; border: 1px solid var(--border); border-radius: 10px;
  color: var(--text); padding: 9px 12px; margin-bottom: 12px; font-size: 14px;
}
button {
  background: var(--accent); color: #fff; border: none; border-radius: 8px;
  padding: 9px 14px; font-size: 14px; font-weight: 600; cursor: pointer;
}
button:hover { background: var(--accent-hover); }
.error { color: var(--danger); font-size: 12px; min-height: 16px; }
.item-list { list-style: none; padding: 0; margin: 0; display: grid; gap: 12px; max-width: 480px; }
.item-list a {
  display: block; background: var(--surface); border: 1px solid var(--border);
  border-radius: 16px; padding: 16px 18px; color: var(--text); text-decoration: none;
}
.item-list a:hover { background: #232945; }
.muted { color: var(--text-muted); font-size: 12px; }
.price { font-family: "JetBrains Mono", ui-monospace, monospace; font-weight: 700; font-size: 18px; }
"""


def _shell(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>{title} — Demo</title>
<style>{_CSS}</style>
</head>
<body>
{body}
</body>
</html>"""


@router.get("/login", response_class=HTMLResponse)
def login_page() -> str:
    body = """
<h1>Вход — Demo</h1>
<div class="card">
  <label for="login">Логин</label>
  <input id="login" value="alice">
  <label for="password">Пароль</label>
  <input id="password" type="password" value="alice123">
  <button id="submit">Войти</button>
  <p id="error" class="error"></p>
</div>
<script>
document.getElementById("submit").addEventListener("click", async () => {
  const login = document.getElementById("login").value;
  const password = document.getElementById("password").value;
  const errorEl = document.getElementById("error");
  errorEl.textContent = "";
  const resp = await fetch("/api/auth/login", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({login, password}),
  });
  if (!resp.ok) {
    errorEl.textContent = "Неверный логин или пароль";
    return;
  }
  const data = await resp.json();
  localStorage.setItem("demo_token", data.token);
  window.location.href = "/catalog";
});
</script>
"""
    return _shell("Вход", body)


@router.get("/catalog", response_class=HTMLResponse)
def catalog_page() -> str:
    body = """
<h1>Каталог — Demo</h1>
<ul id="items" class="item-list"></ul>
<script>
(async () => {
  const resp = await fetch("/api/catalog");
  const items = await resp.json();
  const list = document.getElementById("items");
  for (const item of items) {
    const a = document.createElement("a");
    a.href = `/catalog/${item.id}`;
    a.innerHTML = `<span class="item-title">${item.title}</span><br>` +
      `<span class="price">${item.price} ₽</span> ` +
      `<span class="muted">${item.stock > 0 ? "в наличии" : "нет в наличии"}</span>`;
    const li = document.createElement("li");
    li.appendChild(a);
    list.appendChild(li);
  }
})();
</script>
"""
    return _shell("Каталог", body)


@router.get("/catalog/{item_id}", response_class=HTMLResponse)
def catalog_item_page(item_id: int) -> str:
    body = f"""
<h1>Товар — Demo</h1>
<div class="card" id="item-card" data-item-id="{item_id}">
  <p class="muted">Загрузка…</p>
</div>
<script>
(async () => {{
  const itemId = {item_id};
  const resp = await fetch(`/api/catalog/${{itemId}}`);
  const card = document.getElementById("item-card");
  if (!resp.ok) {{
    card.innerHTML = "<p>Товар не найден</p>";
    return;
  }}
  const item = await resp.json();
  card.innerHTML = `
    <h2 id="title">${{item.title}}</h2>
    <p class="price" id="price">${{item.price}} ₽</p>
    <p class="muted" id="discount">Скидка: ${{item.discount}}%</p>
    <p class="muted" id="stock">В наличии: ${{item.stock}}</p>
    <button id="buy" ${{item.stock < 1 ? "disabled" : ""}}>Купить</button>
    <p id="error" class="error"></p>
  `;
  document.getElementById("buy").addEventListener("click", async () => {{
    const token = localStorage.getItem("demo_token");
    const headers = {{"Content-Type": "application/json"}};
    if (token) headers["Authorization"] = `Bearer ${{token}}`;
    const orderResp = await fetch("/api/orders", {{
      method: "POST", headers, body: JSON.stringify({{item_id: itemId, qty: 1}}),
    }});
    if (!orderResp.ok) {{
      document.getElementById("error").textContent = "Не удалось оформить заказ";
      return;
    }}
    const order = await orderResp.json();
    window.location.href = `/orders/${{order.id}}`;
  }});
}})();
</script>
"""
    return _shell("Товар", body)


@router.get("/orders/{order_id}", response_class=HTMLResponse)
def order_page(order_id: int) -> str:
    body = f"""
<h1>Заказ — Demo</h1>
<div class="card" id="order-card" data-order-id="{order_id}">
  <p class="muted">Загрузка…</p>
</div>
<script>
(async () => {{
  const resp = await fetch(`/api/orders/{order_id}`);
  const card = document.getElementById("order-card");
  if (!resp.ok) {{
    card.innerHTML = "<p>Заказ не найден</p>";
    return;
  }}
  const order = await resp.json();
  card.innerHTML = `
    <p class="muted">Заказ #${{order.id}}</p>
    <p class="muted">Количество: ${{order.qty}}</p>
    <p class="muted">Скидка: ${{order.discount}}%</p>
    <p class="price" id="total">${{order.total}} ₽</p>
  `;
}})();
</script>
"""
    return _shell("Заказ", body)
