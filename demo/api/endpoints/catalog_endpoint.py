class CatalogEndpoint:
    LIST = "/api/catalog"

    def __init__(self, client):
        self.client = client

    def list(self, query: str | None = None):
        params = {"query": query} if query else None
        return self.client.get(self.LIST, params=params)

    def get(self, item_id: int):
        return self.client.get(f"{self.LIST}/{item_id}")
