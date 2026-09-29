class OrdersEndpoint:
    BASE = "/api/orders"

    def __init__(self, client):
        self.client = client

    def create(self, item_id: int, qty: int = 1, token: str | None = None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return self.client.post(self.BASE, json={"item_id": item_id, "qty": qty}, headers=headers)

    def get(self, order_id: int):
        return self.client.get(f"{self.BASE}/{order_id}")

    def list(self):
        return self.client.get(self.BASE)
