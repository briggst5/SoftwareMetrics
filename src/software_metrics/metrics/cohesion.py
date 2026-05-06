"""
Class-level cohesion via **LCOM** (Lack of Cohesion of Methods), CK-style.

For each class-like unit, instance methods are paired; pairs where **both** methods
reference at least one known instance field are counted as ``joint`` if they share
a field, else ``disjoint``. Then::

    LCOM = max(0, disjoint - joint)

Higher LCOM ⇒ lower cohesion. **Average LCOM** is the mean over all analyzed units.

Field/method use is **heuristic** (identifiers and ``this`` / ``self`` field access).
Rust matches ``impl Type`` to ``struct Type`` in the **same file**.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from tree_sitter import Node

from software_metrics.debug_report import ComputationStep
from software_metrics.discovery import iter_metric_files
from software_metrics.metrics.cyclomatic import PARSERS

COHESION_METRIC_ID = "cohesion"


def _pos_1based(node: Node) -> tuple[int, int]:
    return node.start_point.row + 1, node.start_point.column + 1


def _normalize_under(root: Path, path: Path) -> str:
    return str(path.resolve().relative_to(root.resolve()))


def _lcom_ck(method_field_sets: list[set[str]]) -> int:
    nonempty = [s for s in method_field_sets if s]
    if len(nonempty) < 2:
        return 0
    disjoint = 0
    joint = 0
    for i in range(len(nonempty)):
        for j in range(i + 1, len(nonempty)):
            si, sj = nonempty[i], nonempty[j]
            if si & sj:
                joint += 1
            else:
                disjoint += 1
    return max(0, disjoint - joint)


@dataclass(frozen=True)
class _UnitLcomDebug:
    unit_name: str
    line: int
    col: int
    lcom: int
    instance_fields: set[str]
    # CK-style: only methods that reference >=1 instance field
    method_fields_used: dict[str, set[str]]


def _shared_methods_and_attributes(
    method_fields_used: dict[str, set[str]],
) -> tuple[list[str], list[str], dict[tuple[str, str], list[str]]]:
    """
    Return (shared_methods, shared_attributes, shared_fields_by_pair).

    - shared_methods: methods that share >=1 attribute with any other method
    - shared_attributes: attributes used by >=2 methods (i.e., appear in any overlap)
    - shared_fields_by_pair: (m1, m2) -> sorted shared field names (may be empty)
    """
    methods = sorted(method_fields_used.keys())
    shared_methods: set[str] = set()
    shared_attrs: set[str] = set()
    shared_by_pair: dict[tuple[str, str], list[str]] = {}

    for i, mi in enumerate(methods):
        for mj in methods[i + 1 :]:
            shared = method_fields_used[mi] & method_fields_used[mj]
            shared_sorted = sorted(shared)
            shared_by_pair[(mi, mj)] = shared_sorted
            if shared_sorted:
                shared_methods.add(mi)
                shared_methods.add(mj)
                shared_attrs.update(shared_sorted)

    return (sorted(shared_methods), sorted(shared_attrs), shared_by_pair)


def _ts_fields_used(method_body: Node, fields: set[str]) -> set[str]:
    used: set[str] = set()

    def walk(n: Node) -> None:
        if n.type == "member_expression":
            obj = n.child_by_field_name("object")
            prop = n.child_by_field_name("property")
            if obj is not None and obj.type == "this" and prop is not None:
                name = prop.text.decode(errors="replace").lstrip("#")
                if name in fields:
                    used.add(name)
        elif n.type == "identifier":
            t = n.text.decode(errors="replace")
            if t in fields:
                used.add(t)
        for ch in n.children:
            walk(ch)

    walk(method_body)
    return used


def _rust_fields_used(body: Node, fields: set[str]) -> set[str]:
    used: set[str] = set()

    def walk(n: Node) -> None:
        if n.type == "field_expression":
            chs = list(n.children)
            if chs and chs[0].type == "self":
                for ch in chs:
                    if ch.type == "field_identifier":
                        name = ch.text.decode(errors="replace")
                        if name in fields:
                            used.add(name)
        elif n.type == "identifier":
            t = n.text.decode(errors="replace")
            if t in fields:
                used.add(t)
        for ch in n.children:
            walk(ch)

    walk(body)
    return used


def _kotlin_fields_used(body: Node, fields: set[str]) -> set[str]:
    used: set[str] = set()

    def walk(n: Node) -> None:
        if n.type == "identifier":
            t = n.text.decode(errors="replace")
            if t in fields:
                used.add(t)
        for ch in n.children:
            walk(ch)

    walk(body)
    return used


def _ts_extract_class_fields(cls_body: Node) -> set[str]:
    names: set[str] = set()
    for ch in cls_body.children:
        if ch.type == "public_field_definition":
            for part in ch.children:
                if part.type == "property_identifier":
                    names.add(part.text.decode(errors="replace"))
                elif part.type == "private_property_identifier":
                    names.add(part.text.decode(errors="replace").lstrip("#"))
    return names


def _ts_method_bodies(class_node: Node) -> list[tuple[str, Node]]:
    out: list[tuple[str, Node]] = []
    body = class_node.child_by_field_name("body")
    if body is None:
        return out
    for ch in body.children:
        if ch.type == "method_definition":
            name_node = ch.child_by_field_name("name")
            if name_node is None:
                for c in ch.children:
                    if c.type == "property_identifier":
                        name_node = c
                        break
            label = name_node.text.decode(errors="replace") if name_node else "method"
            mb = ch.child_by_field_name("body")
            if mb is not None:
                out.append((label, mb))
    return out


def _lcom_ts_class(
    class_node: Node, *, debug: bool = False
) -> tuple[int, str] | _UnitLcomDebug | None:
    body = class_node.child_by_field_name("body")
    if body is None:
        return None
    fields = _ts_extract_class_fields(body)
    methods = _ts_method_bodies(class_node)
    if len(methods) < 2:
        return None
    name_node = class_node.child_by_field_name("name")
    cname = name_node.text.decode(errors="replace") if name_node else "class"
    if not fields:
        if debug:
            line, col = _pos_1based(class_node)
            return _UnitLcomDebug(
                unit_name=cname,
                line=line,
                col=col,
                lcom=0,
                instance_fields=set(),
                method_fields_used={},
            )
        return (0, cname)

    used_by_method = {lbl: _ts_fields_used(mb, fields) for lbl, mb in methods}
    used_by_method_nonempty = {m: s for m, s in used_by_method.items() if s}
    lcom = _lcom_ck(list(used_by_method.values()))
    if not debug:
        return (lcom, cname)
    line, col = _pos_1based(class_node)
    return _UnitLcomDebug(
        unit_name=cname,
        line=line,
        col=col,
        lcom=lcom,
        instance_fields=fields,
        method_fields_used=used_by_method_nonempty,
    )


def _kotlin_class_body(class_node: Node) -> Node | None:
    for ch in class_node.children:
        if ch.type == "class_body":
            return ch
    return None


def _kotlin_extract_fields(class_node: Node) -> set[str]:
    names: set[str] = set()
    pc = None
    for ch in class_node.children:
        if ch.type == "primary_constructor":
            pc = ch
            break
    if pc is not None:
        for ch in pc.children:
            if ch.type == "class_parameters":
                for param in ch.children:
                    if param.type == "class_parameter":
                        for p in param.children:
                            if p.type == "identifier":
                                names.add(p.text.decode(errors="replace"))
    body = _kotlin_class_body(class_node)
    if body is not None:
        for ch in body.children:
            if ch.type == "property_declaration":
                for sub in ch.children:
                    if sub.type == "variable_declaration":
                        for v in sub.children:
                            if v.type == "identifier":
                                names.add(v.text.decode(errors="replace"))
    return names


def _kotlin_method_bodies(class_node: Node) -> list[tuple[str, Node]]:
    out: list[tuple[str, Node]] = []
    body = _kotlin_class_body(class_node)
    if body is None:
        return out
    for ch in body.children:
        if ch.type == "function_declaration":
            ident = ch.child_by_field_name("name")
            label = ident.text.decode(errors="replace") if ident else "fun"
            fb = None
            for c in ch.children:
                if c.type == "function_body":
                    fb = c
                    break
            if fb is not None:
                out.append((label, fb))
    return out


def _lcom_kotlin_class(
    class_node: Node, *, debug: bool = False
) -> tuple[int, str] | _UnitLcomDebug | None:
    fields = _kotlin_extract_fields(class_node)
    methods = _kotlin_method_bodies(class_node)
    if len(methods) < 2:
        return None
    name_node = class_node.child_by_field_name("name")
    if name_node is None:
        for ch in class_node.children:
            if ch.type == "identifier":
                name_node = ch
                break
    cname = name_node.text.decode(errors="replace") if name_node else "class"
    if not fields:
        if debug:
            line, col = _pos_1based(class_node)
            return _UnitLcomDebug(
                unit_name=cname,
                line=line,
                col=col,
                lcom=0,
                instance_fields=set(),
                method_fields_used={},
            )
        return (0, cname)

    used_by_method = {lbl: _kotlin_fields_used(mb, fields) for lbl, mb in methods}
    used_by_method_nonempty = {m: s for m, s in used_by_method.items() if s}
    lcom = _lcom_ck(list(used_by_method.values()))
    if not debug:
        return (lcom, cname)
    line, col = _pos_1based(class_node)
    return _UnitLcomDebug(
        unit_name=cname,
        line=line,
        col=col,
        lcom=lcom,
        instance_fields=fields,
        method_fields_used=used_by_method_nonempty,
    )


def _rust_struct_fields(struct_node: Node) -> set[str]:
    names: set[str] = set()
    for ch in struct_node.children:
        if ch.type == "field_declaration_list":
            for fd in ch.children:
                if fd.type == "field_declaration":
                    for part in fd.children:
                        if part.type == "field_identifier":
                            names.add(part.text.decode(errors="replace"))
    return names


def _rust_impl_methods(impl_node: Node) -> list[tuple[str, Node]]:
    out: list[tuple[str, Node]] = []
    for ch in impl_node.children:
        if ch.type == "declaration_list":
            for item in ch.children:
                if item.type == "function_item":
                    ident = item.child_by_field_name("name")
                    label = ident.text.decode(errors="replace") if ident else "fn"
                    body = item.child_by_field_name("body")
                    if body is not None:
                        out.append((label, body))
    return out


def _rust_impl_type_name(impl_node: Node) -> str | None:
    for ch in impl_node.children:
        if ch.type == "type_identifier":
            return ch.text.decode(errors="replace")
        if ch.type == "scoped_type_identifier":

            def last_type_id(n: Node) -> str | None:
                if n.type == "type_identifier":
                    return n.text.decode(errors="replace")
                last: str | None = None
                for c in n.children:
                    v = last_type_id(c)
                    if v:
                        last = v
                return last

            return last_type_id(ch)
    return None


def _rust_find_struct(root: Node, name: str) -> Node | None:

    def walk(n: Node) -> Node | None:
        if n.type == "struct_item":
            tid = n.child_by_field_name("name")
            if tid is not None and tid.text.decode(errors="replace") == name:
                return n
        for ch in n.children:
            r = walk(ch)
            if r is not None:
                return r
        return None

    return walk(root)


def _lcom_rust_impl(
    impl_node: Node, tree_root: Node, *, debug: bool = False
) -> tuple[int, str] | _UnitLcomDebug | None:
    tname = _rust_impl_type_name(impl_node)
    if not tname:
        return None
    struct_n = _rust_find_struct(tree_root, tname)
    if struct_n is None:
        return None
    fields = _rust_struct_fields(struct_n)
    methods = _rust_impl_methods(impl_node)
    if len(methods) < 2:
        return None
    if not fields:
        if debug:
            line, col = _pos_1based(impl_node)
            return _UnitLcomDebug(
                unit_name=tname,
                line=line,
                col=col,
                lcom=0,
                instance_fields=set(),
                method_fields_used={},
            )
        return (0, tname)

    used_by_method = {lbl: _rust_fields_used(mb, fields) for lbl, mb in methods}
    used_by_method_nonempty = {m: s for m, s in used_by_method.items() if s}
    lcom = _lcom_ck(list(used_by_method.values()))
    if not debug:
        return (lcom, tname)
    line, col = _pos_1based(impl_node)
    return _UnitLcomDebug(
        unit_name=tname,
        line=line,
        col=col,
        lcom=lcom,
        instance_fields=fields,
        method_fields_used=used_by_method_nonempty,
    )


@dataclass
class CohesionProjectResult:
    root: Path
    units_analyzed: int
    average_lcom: float | None
    total_lcom: int
    files_scanned: int
    files_with_errors: list[tuple[str, str]] = field(default_factory=list)
    debug_steps: list[ComputationStep] | None = None

    def summary_text(self) -> str:
        if self.units_analyzed == 0:
            return (
                "Cohesion (average LCOM over class-like units): n/a\n"
                f"  (no qualifying classes / impls found under {self.root})\n"
                f"  Files scanned: {self.files_scanned}"
            )
        avg = self.average_lcom
        assert avg is not None
        return (
            "Cohesion (average LCOM — Lack of Cohesion of Methods, CK-style)\n"
            f"  Class / impl units analyzed: {self.units_analyzed}\n"
            f"  Sum of LCOM scores: {self.total_lcom}\n"
            f"  Average LCOM: {avg:.4f}\n"
            f"  (Higher LCOM ⇒ lower cohesion; minimum 0 per unit.)\n"
            f"  Files scanned: {self.files_scanned}"
        )

    def debug_text(self) -> str:
        from software_metrics.debug_report import format_computation_steps

        if not self.debug_steps:
            return ""
        return format_computation_steps(
            COHESION_METRIC_ID,
            self.debug_steps,
            header=f"Project root: {self.root}",
        )


def _analyze_file(
    path: Path, lang: str, root: Path, *, debug: bool = False
) -> tuple[list[tuple[int, str, int, int]] | list[_UnitLcomDebug], str | None]:
    """
    Return list of (lcom, unit_name, line, col) and optional error.
    """
    parser = PARSERS[lang]
    try:
        text = path.read_bytes()
    except OSError as e:
        return [], str(e)
    tree = parser.parse(text)
    if tree.root_node.has_error:
        return [], "parse tree has errors (skipped)"
    rows: list[tuple[int, str, int, int]] = []
    debug_rows: list[_UnitLcomDebug] = []
    root_node = tree.root_node

    if lang in ("ts", "tsx"):

        def walk_ts(n: Node) -> None:
            if n.type == "class_declaration":
                r = _lcom_ts_class(n, debug=debug)
                if r is not None:
                    if isinstance(r, _UnitLcomDebug):
                        debug_rows.append(r)
                    else:
                        lcom, cname = r
                        line, col = _pos_1based(n)
                        rows.append((lcom, cname, line, col))
            for ch in n.children:
                walk_ts(ch)

        walk_ts(root_node)
        return (debug_rows if debug else rows), None

    if lang == "kotlin":

        def walk_k(n: Node) -> None:
            if n.type == "class_declaration":
                r = _lcom_kotlin_class(n, debug=debug)
                if r is not None:
                    if isinstance(r, _UnitLcomDebug):
                        debug_rows.append(r)
                    else:
                        lcom, cname = r
                        line, col = _pos_1based(n)
                        rows.append((lcom, cname, line, col))
            for ch in n.children:
                walk_k(ch)

        walk_k(root_node)
        return (debug_rows if debug else rows), None

    if lang == "rust":

        def walk_r(n: Node) -> None:
            if n.type == "impl_item":
                r = _lcom_rust_impl(n, root_node, debug=debug)
                if r is not None:
                    if isinstance(r, _UnitLcomDebug):
                        debug_rows.append(r)
                    else:
                        lcom, tname = r
                        line, col = _pos_1based(n)
                        rows.append((lcom, tname, line, col))
            for ch in n.children:
                walk_r(ch)

        walk_r(root_node)
        return (debug_rows if debug else rows), None

    return [], None


def analyze_cohesion_project(root: Path, *, debug: bool = False) -> CohesionProjectResult:
    root = root.resolve()
    errors: list[tuple[str, str]] = []
    all_rows: list[tuple[str, int, str, int, int]] = []
    all_debug_rows: list[tuple[str, _UnitLcomDebug]] = []
    files_ok = 0

    for path, lang in iter_metric_files(root):
        rows, err = _analyze_file(path, lang, root, debug=debug)
        if err:
            errors.append((str(path), err))
            continue
        if not rows:
            files_ok += 1
            continue
        rel = _normalize_under(root, path)
        if debug:
            assert isinstance(rows, list)
            for dr in rows:
                assert isinstance(dr, _UnitLcomDebug)
                all_rows.append((rel, dr.lcom, dr.unit_name, dr.line, dr.col))
                all_debug_rows.append((rel, dr))
        else:
            assert isinstance(rows, list)
            for lcom, unit, line, col in rows:
                all_rows.append((rel, lcom, unit, line, col))
        files_ok += 1

    n_units = len(all_rows)
    total = sum(t[1] for t in all_rows)
    avg: float | None = (total / n_units) if n_units else None

    dbg: list[ComputationStep] | None = [] if debug else None
    if debug and dbg is not None:
        for rel, dr in sorted(all_debug_rows, key=lambda x: (x[0], x[1].unit_name)):
            apath = (root / Path(rel)).resolve()

            inst_fields_sorted = sorted(dr.instance_fields)
            for m in sorted(dr.method_fields_used.keys()):
                used_sorted = sorted(dr.method_fields_used[m])
                dbg.append(
                    ComputationStep(
                        COHESION_METRIC_ID,
                        str(apath),
                        dr.unit_name,
                        dr.line,
                        dr.col,
                        "method_fields_used",
                        0,
                        f"method={m} uses={used_sorted} (instance_fields={inst_fields_sorted})",
                    )
                )

            shared_methods, shared_attrs, shared_by_pair = _shared_methods_and_attributes(
                dr.method_fields_used
            )
            for (m1, m2), shared_fields in sorted(shared_by_pair.items(), key=lambda kv: kv[0]):
                dbg.append(
                    ComputationStep(
                        COHESION_METRIC_ID,
                        str(apath),
                        dr.unit_name,
                        dr.line,
                        dr.col,
                        "method_pair_shared_fields",
                        0,
                        f"pair=({m1},{m2}) shared={shared_fields}",
                    )
                )

            dbg.append(
                ComputationStep(
                    COHESION_METRIC_ID,
                    str(apath),
                    dr.unit_name,
                    dr.line,
                    dr.col,
                    "shared_attributes",
                    0,
                    f"{shared_attrs}",
                )
            )
            dbg.append(
                ComputationStep(
                    COHESION_METRIC_ID,
                    str(apath),
                    dr.unit_name,
                    dr.line,
                    dr.col,
                    "shared_methods",
                    0,
                    f"{shared_methods}",
                )
            )

            dbg.append(
                ComputationStep(
                    COHESION_METRIC_ID,
                    str(apath),
                    dr.unit_name,
                    dr.line,
                    dr.col,
                    "LCOM",
                    dr.lcom,
                    "CK-style LCOM for this class/impl (max(0, disjoint_pairs - joint_pairs))",
                )
            )

    return CohesionProjectResult(
        root=root,
        units_analyzed=n_units,
        average_lcom=avg,
        total_lcom=total,
        files_scanned=files_ok,
        files_with_errors=errors,
        debug_steps=dbg if debug else None,
    )
