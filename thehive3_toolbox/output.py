"""Plain-text and JSON rendering. Diagnostics go to stderr, so stdout stays pipeable."""

from __future__ import annotations

import json
import sys
from typing import Any, Iterable, List, Sequence, Tuple


def text(value: Any) -> str:
    if value is None or value == "" or value == []:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    return str(value)


def print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def print_fields(pairs: Iterable[Tuple[str, Any]]) -> None:
    pairs = list(pairs)
    width = max(len(label) for label, _ in pairs)
    for label, value in pairs:
        print(f"{label:<{width}}  {text(value)}")


def print_table(headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> None:
    cells: List[List[str]] = [list(headers)] + [[text(v) for v in row] for row in rows]
    widths = [max(len(row[i]) for row in cells) for i in range(len(headers))]
    for row in cells:
        print("  ".join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip())


def note(message: str) -> None:
    print(message, file=sys.stderr)
