class CatalogPage:
    URL = "/catalog"

    def __init__(self, page):
        self.page = page

    def open(self):
        self.page.goto(self.URL)
        return self

    def item_titles(self) -> list[str]:
        self.page.wait_for_selector(".item-list a")
        return self.page.locator(".item-title").all_inner_texts()
