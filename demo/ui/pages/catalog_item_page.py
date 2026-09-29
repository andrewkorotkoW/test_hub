class CatalogItemPage:
    URL = "/catalog"

    def __init__(self, page):
        self.page = page

    def open(self, item_id: int):
        self.page.goto(f"{self.URL}/{item_id}")
        return self

    def price_text(self) -> str:
        self.page.wait_for_selector("#price")
        return self.page.locator("#price").inner_text()

    def buy(self):
        self.page.click("#buy")
        return self
