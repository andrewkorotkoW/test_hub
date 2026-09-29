class AuthEndpoint:
    LOGIN = "/api/auth/login"
    ME = "/api/auth/me"

    def __init__(self, client):
        self.client = client

    def login(self, login: str, password: str):
        return self.client.post(self.LOGIN, json={"login": login, "password": password})

    def me(self, token: str | None = None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return self.client.get(self.ME, headers=headers)
