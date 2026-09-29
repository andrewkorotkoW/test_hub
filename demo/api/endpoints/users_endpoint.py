class UsersEndpoint:
    BASE = "/api/users"

    def __init__(self, client):
        self.client = client

    def list(self):
        return self.client.get(self.BASE)

    def get(self, user_id: int):
        return self.client.get(f"{self.BASE}/{user_id}")
