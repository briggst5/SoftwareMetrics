"""
Depth of Inheritance Tree (**DIT**) for Kotlin and TypeScript classes.

Each ``class`` contributes one row. **extends** / Kotlin superclass delegation
edges are resolved by simple type name to another class in the project (same-file
match preferred). If the superclass is not defined in the tree, depth assumes an
external root (**DIT** includes one extra level).

Rust has no OO class inheritance in this sense and is skipped (no class rows).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from tree_sitter import Node

from software_metrics.debug_report import ComputationStep
from software_metrics.discovery import iter_metric_files
from software_metrics.metrics.cyclomatic import PARSERS

DIT_METRIC_ID = "dit"


def _pos_1based(node: Node) -> tuple[int, int]:
    return node.start_point.row + 1, node.start_point.column + 1


def _normalize_under(root: Path, path: Path) -> str:
    return str(path.resolve().relative_to(root.resolve()))


def _last_identifier_text(node: Node) -> str | None:
    """Rightmost identifier (e.g. ``Component`` in ``React.Component``)."""
    last: str | None = None

    def walk(n: Node) -> None:
        nonlocal last
        if n.type == "identifier":
            last = n.text.decode(errors="replace")
        if n.type == "property_identifier":
            last = n.text.decode(errors="replace").lstrip("#")
        for ch in n.children:
            walk(ch)

    walk(node)
    return last


def _ts_super_name(class_node: Node) -> str | None:
    for ch in class_node.children:
        if ch.type != "class_heritage":
            continue
        for g in ch.children:
            if g.type != "extends_clause":
                continue
            # extends_clause → identifier | nested_identifier | member_expression | …
            for sub in g.children:
                if sub.type in ("identifier", "nested_identifier"):
                    li = _last_identifier_text(sub)
                    if li:
                        return li
                elif sub.type == "member_expression":
                    li = _last_identifier_text(sub)
                    if li:
                        return li
                else:
                    li = _last_identifier_text(sub)
                    if li:
                        return li
    return None


def _kotlin_super_name(class_node: Node) -> str | None:
    for ch in class_node.children:
        if ch.type != "delegation_specifiers":
            continue
        for spec in ch.children:
            if spec.type != "delegation_specifier":
                continue
            for sub in spec.children:
                if sub.type != "constructor_invocation":
                    continue
                for inner in sub.children:
                    if inner.type == "user_type":
                        for c in inner.children:
                            if c.type == "identifier":
                                return c.text.decode(errors="replace")
        break
    return None


def _ts_class_name(class_node: Node) -> str | None:
    tid = class_node.child_by_field_name("name")
    if tid is None:
        for ch in class_node.children:
            if ch.type == "type_identifier":
                return ch.text.decode(errors="replace")
        return None
    return tid.text.decode(errors="replace")


def _kotlin_class_name(class_node: Node) -> str | None:
    tid = class_node.child_by_field_name("name")
    if tid is None:
        for ch in class_node.children:
            if ch.type == "identifier":
                return ch.text.decode(errors="replace")
        return None
    return tid.text.decode(errors="replace")


def _collect_classes_from_file(
    path: Path,
    lang: str,
    root: Path,
) -> tuple[list[tuple[str, str, str | None, int, int]], str | None]:
    parser = PARSERS[lang]
    try:
        text = path.read_bytes()
    except OSError as e:
        return [], str(e)
    tree = parser.parse(text)
    if tree.root_node.has_error:
        return [], "parse tree has errors (skipped)"
    rel = _normalize_under(root, path)
    rows: list[tuple[str, str, str | None, int, int]] = []

    def walk_ts(n: Node) -> None:
        if n.type == "class_declaration":
            cname = _ts_class_name(n)
            if cname:
                sup = _ts_super_name(n)
                line, col = _pos_1based(n)
                rows.append((rel, cname, sup, line, col))
        for ch in n.children:
            walk_ts(ch)

    def walk_kotlin(n: Node) -> None:
        if n.type == "class_declaration":
            cname = _kotlin_class_name(n)
            if cname:
                sup = _kotlin_super_name(n)
                line, col = _pos_1based(n)
                rows.append((rel, cname, sup, line, col))
        for ch in n.children:
            walk_kotlin(ch)

    if lang in ("ts", "tsx"):
        walk_ts(tree.root_node)
    elif lang == "kotlin":
        walk_kotlin(tree.root_node)

    return rows, None


def _compute_dit(
    rows: list[tuple[str, str, str | None, int, int]],
) -> tuple[dict[tuple[str, str], int], dict[tuple[str, str], tuple[int, int, str | None]]]:
    """
    Return depths[(file, class)] and display meta keyed same (last row wins).
    """
    locations: dict[tuple[str, str], str | None] = {}
    display: dict[tuple[str, str], tuple[int, int, str | None]] = {}
    for rel, cname, sup, line, col in rows:
        key = (rel, cname)
        locations[key] = sup
        display[key] = (line, col, sup)

    by_name: defaultdict[str, list[str]] = defaultdict(list)
    for fr, name in locations:
        by_name[name].append(fr)

    def resolve_parent_file(child_file: str, parent_name: str) -> str | None:
        files = by_name.get(parent_name)
        if not files:
            return None
        if child_file in files:
            return child_file
        return sorted(files)[0]

    memo: dict[tuple[str, str], int] = {}

    def dit_depth(file_rel: str, cls_name: str, stack: set[tuple[str, str]]) -> int:
        key = (file_rel, cls_name)
        if key in memo:
            return memo[key]
        if key in stack:
            return 1
        stack.add(key)
        try:
            parent = locations.get(key)
            if parent is None:
                memo[key] = 1
                return 1
            pf = resolve_parent_file(file_rel, parent)
            if pf is None:
                memo[key] = 2
                return 2
            d = 1 + dit_depth(pf, parent, stack)
            memo[key] = d
            return d
        finally:
            stack.discard(key)

    depths: dict[tuple[str, str], int] = {}
    for key in locations:
        depths[key] = dit_depth(key[0], key[1], set())

    return depths, display


@dataclass
class DitProjectResult:
    root: Path
    classes_count: int
    average_dit: float | None
    maximum_dit: int
    files_scanned: int
    files_with_errors: list[tuple[str, str]] = field(default_factory=list)
    debug_steps: list[ComputationStep] | None = None

    def summary_text(self) -> str:
        if self.classes_count == 0:
            return (
                "Depth of inheritance tree (average DIT): n/a\n"
                f"  (no classes found under {self.root})\n"
                f"  Files scanned: {self.files_scanned}"
            )
        avg = self.average_dit
        assert avg is not None
        return (
            "Depth of inheritance tree (DIT)\n"
            f"  Classes analyzed: {self.classes_count}\n"
            f"  Average DIT: {avg:.4f}\n"
            f"  Maximum DIT: {self.maximum_dit}\n"
            "  (Only extends / class inheritance edges; composition not counted.)\n"
            f"  Files scanned: {self.files_scanned}"
        )

    def debug_text(self) -> str:
        from software_metrics.debug_report import format_computation_steps

        if not self.debug_steps:
            return ""
        return format_computation_steps(
            DIT_METRIC_ID,
            self.debug_steps,
            header=f"Project root: {self.root}",
        )


def analyze_dit_project(root: Path, *, debug: bool = False) -> DitProjectResult:
    root = root.resolve()
    errors: list[tuple[str, str]] = []
    all_rows: list[tuple[str, str, str | None, int, int]] = []
    files_ok = 0

    for path, lang in iter_metric_files(root):
        if lang not in ("ts", "tsx", "kotlin"):
            files_ok += 1
            continue
        rows, err = _collect_classes_from_file(path, lang, root)
        if err:
            errors.append((str(path), err))
            continue
        all_rows.extend(rows)
        files_ok += 1

    depths, display = _compute_dit(all_rows)
    n = len(depths)
    if n == 0:
        return DitProjectResult(
            root=root,
            classes_count=0,
            average_dit=None,
            maximum_dit=0,
            files_scanned=files_ok,
            files_with_errors=errors,
            debug_steps=[] if debug else None,
        )

    vals = list(depths.values())
    avg = sum(vals) / len(vals)
    mx = max(vals)

    dbg: list[ComputationStep] | None = [] if debug else None
    if debug and dbg is not None:
        for file_rel, cls_name in sorted(depths.keys(), key=lambda k: (k[0], k[1])):
            line, col, _sup = display[(file_rel, cls_name)]
            d = depths[(file_rel, cls_name)]
            apath = (root / Path(file_rel)).resolve()
            dbg.append(
                ComputationStep(
                    DIT_METRIC_ID,
                    str(apath),
                    cls_name,
                    line,
                    col,
                    "DIT",
                    d,
                    "Depth through internal/external superclass chain",
                )
            )

    return DitProjectResult(
        root=root,
        classes_count=n,
        average_dit=avg,
        maximum_dit=mx,
        files_scanned=files_ok,
        files_with_errors=errors,
        debug_steps=dbg if debug else None,
    )
