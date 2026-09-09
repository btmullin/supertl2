"""Global session-backed training filter (category / workout type).

Lets a user narrow the dashboard, calendar, and season views down to a
single category branch (e.g. "Running" including "Trail Running") without
threading query-string params through every page.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Set

from flask import session

from ..db.base import sqla_db
from ..models import Category, WorkoutType

SESSION_KEY = "training_filter"


@dataclass
class TrainingFilter:
    category_id: Optional[int] = None
    workout_type_ids: List[int] = field(default_factory=list)

    @property
    def is_active(self) -> bool:
        return self.category_id is not None or bool(self.workout_type_ids)


def _build_children_map():
    rows = sqla_db.session.query(Category.id, Category.parent_id).all()
    children = {}
    for cid, parent_id in rows:
        children.setdefault(parent_id, []).append(cid)
    return children


def expand_category_ids(category_id: Optional[int]) -> Set[int]:
    """Return category_id plus all of its descendant category ids."""
    if category_id is None:
        return set()

    children = _build_children_map()
    stack = [category_id]
    result: Set[int] = set()
    while stack:
        current = stack.pop()
        result.add(current)
        stack.extend(children.get(current, []))
    return result


def get_active_filter() -> TrainingFilter:
    raw = session.get(SESSION_KEY)
    if not raw:
        return TrainingFilter()

    category_id = raw.get("category_id")
    workout_type_ids = raw.get("workout_type_ids") or []

    # Re-validate against the DB so stale/deleted ids don't silently persist.
    if category_id is not None:
        exists = sqla_db.session.query(Category.id).filter(Category.id == category_id).first()
        if exists is None:
            category_id = None

    if workout_type_ids:
        valid_ids = {
            wid for (wid,) in sqla_db.session.query(WorkoutType.id).filter(WorkoutType.id.in_(workout_type_ids)).all()
        }
        workout_type_ids = [wid for wid in workout_type_ids if wid in valid_ids]

    return TrainingFilter(category_id=category_id, workout_type_ids=workout_type_ids)


def set_active_filter(category_id: Optional[int] = None, workout_type_ids: Optional[List[int]] = None) -> None:
    session[SESSION_KEY] = {
        "category_id": category_id,
        "workout_type_ids": workout_type_ids or [],
    }


def clear_active_filter() -> None:
    session.pop(SESSION_KEY, None)


def apply_filter_to_query(query, training_log_model, training_filter: Optional[TrainingFilter]):
    """Apply the active filter's category/workout-type constraints to a query.

    `training_log_model` is the TrainingLogData model/alias already joined
    into `query`.
    """
    if training_filter is None or not training_filter.is_active:
        return query

    if training_filter.category_id is not None:
        category_ids = expand_category_ids(training_filter.category_id)
        query = query.filter(training_log_model.categoryId.in_(category_ids))

    if training_filter.workout_type_ids:
        query = query.filter(training_log_model.workoutTypeId.in_(training_filter.workout_type_ids))

    return query


def get_category_tree_for_filter():
    """Flat list of categories ordered for an indented <select>, with depth."""
    cats = sqla_db.session.query(Category.id, Category.parent_id, Category.name).all()

    children = {}
    name_lookup = {}
    for cid, parent_id, name in cats:
        children.setdefault(parent_id, []).append(cid)
        name_lookup[cid] = name

    for child_list in children.values():
        child_list.sort(key=lambda cid: name_lookup.get(cid, ""))

    out = []

    def walk(parent_id, depth):
        for cid in children.get(parent_id, []):
            out.append({"id": cid, "name": name_lookup[cid], "depth": depth})
            walk(cid, depth + 1)

    walk(None, 0)
    return out
