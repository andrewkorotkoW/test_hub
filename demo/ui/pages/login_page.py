class LoginPage:
    URL = "/login"

    def __init__(self, page):
        self.page = page

    def open(self):
        self.page.goto(self.URL)
        return self

    def login(self, login: str, password: str):
        self.page.fill("#login", login)
        self.page.fill("#password", password)
        self.page.click("#submit")
        return self

    def error_text(self) -> str:
        return self.page.locator("#error").inner_text()
