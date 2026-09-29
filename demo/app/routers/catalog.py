from fastapi import APIRouter, HTTPException

from .. import store

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


@router.get("")
def list_catalog(query: str | None = None) -> list[dict]:
    items = list(store.CATALOG.values())
    if query:
        needle = query.lower()
        items = [item for item in items if needle in item["title"].lower()]
    return items


@router.get("/{item_id}")
def get_item(item_id: int) -> dict:
    item = store.CATALOG.get(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="товар не найден")
    return item
