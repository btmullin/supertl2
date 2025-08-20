# app/services/category_paths.py
from typing import Dict, Optional, Any, Tuple
from ..models.category import Category

CategoryNode = Tuple[str, Optional[int]]  # (name, parent_id)

def build_category_cache(session) -> Dict[int, CategoryNode]:
    rows = session.query(Category.id, Category.name, Category.parent_id).all()
    # {id: (name, parent_id)}
    return {cid: (name, parent_id) for cid, name, parent_id in rows}

def category_full_path_from_id(
    category_id: Optional[int],
    cache: Dict[int, CategoryNode],
    sep: str = " : ",
    uncategorized_label: str = "Uncategorized",
) -> str:
    if not category_id:
        return uncategorized_label

    parts = []
    current = category_id
    seen = set()  # guard against accidental cycles

    while current is not None:
        if current in seen:
            parts.insert(0, f"[cycle:{current}]")
            break
        seen.add(current)

        node = cache.get(current)
        if not node:
            # unknown id; include the id so you can spot data issues
            parts.insert(0, f"[{current}]")
            break

        name, parent_id = node
        parts.insert(0, name)
        current = parent_id

    return sep.join(parts)
