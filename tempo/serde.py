"""Generic JSON (de)serialization for Tempo's frozen dataclasses.

Dates are ISO strings, tuples become lists, nested dataclasses become objects. `from_jsonable` rebuilds
any annotated dataclass from that form, so every record type round-trips without per-class code.
"""

import json
import types
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints


def to_jsonable(obj: Any) -> Any:
    """Convert dataclasses, dates, and tuples into JSON-ready primitives."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_jsonable(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, datetime | date):
        return obj.isoformat()
    if isinstance(obj, list | tuple):
        return [to_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    return obj


def from_jsonable(tp: Any, data: Any) -> Any:
    """Rebuild a value of annotated type `tp` from its JSON form."""
    if data is None:
        return None
    if is_dataclass(tp):
        return _dataclass_from(tp, data)
    origin = get_origin(tp)
    if origin in (Union, types.UnionType):
        inner = [a for a in get_args(tp) if a is not type(None)]
        return from_jsonable(inner[0], data)
    if origin is tuple:
        args = get_args(tp)
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(from_jsonable(args[0], x) for x in data)
        return tuple(from_jsonable(a, x) for a, x in zip(args, data, strict=True))
    if origin is list:
        return [from_jsonable(get_args(tp)[0], x) for x in data]
    if origin is dict:
        _, value_type = get_args(tp)
        return {k: from_jsonable(value_type, v) for k, v in data.items()}
    if origin is Literal:
        return data
    if tp is datetime:
        return datetime.fromisoformat(data)
    if tp is date:
        return date.fromisoformat(data)
    return data


def _dataclass_from[D](tp: type[D], data: dict[str, Any]) -> D:
    hints = get_type_hints(tp)
    kwargs = {f.name: from_jsonable(hints[f.name], data[f.name]) for f in fields(tp) if f.name in data}
    return tp(**kwargs)


def dump_json(obj: Any, path: Path) -> None:
    """Write `obj` as stable, pretty JSON (sorted keys, trailing newline)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_jsonable(obj), indent=1, sort_keys=True) + "\n")


def load_json(tp: Any, path: Path) -> Any:
    """Read JSON from `path` into annotated type `tp`."""
    return from_jsonable(tp, json.loads(path.read_text()))
