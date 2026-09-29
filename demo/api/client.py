"""Тонкая обёртка над requests.Session — добавляет base_url ко всем путям, как
самостоятельный http-клиент api/endpoints/*.py (в стиле auto_tests_vshgu:
self.client.<verb>(путь), см. app/core/coverage.py::discover_backend_routes)."""
import requests


class HttpClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()

    def get(self, path: str, **kwargs):
        return self.session.get(self.base_url + path, **kwargs)

    def post(self, path: str, **kwargs):
        return self.session.post(self.base_url + path, **kwargs)

    def put(self, path: str, **kwargs):
        return self.session.put(self.base_url + path, **kwargs)

    def delete(self, path: str, **kwargs):
        return self.session.delete(self.base_url + path, **kwargs)
