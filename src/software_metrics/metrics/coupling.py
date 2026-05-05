"""
File-level coupling via internal dependency fan-in / fan-out.

Each scanned source file is a **module**. **Fan-out** is the number of distinct
project files it depends on; **fan-in** is the number of distinct project files
that depend on it. Only edges resolved to another scanned file under ``--root``
are counted (stdlib, npm packages, and unresolved paths are ignored).

Rust resolution handles ``crate::`` / ``super::``, ``mod foo;`` file siblings,
and conservative ``use`` path→file mapping under ``src/``. TypeScript resolves
relative ``./`` / ``../`` specifiers. Kotlin resolves ``import a.b.C`` by
matching ``**/a/b/C.kt`` under the tree.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from tree_sitter import Node

from software_metrics.debug_report import ComputationStep
from software_metrics.metrics.cyclomatic import PARSERS, iter_metric_files

COUPLING_METRIC_ID = "coupling"


def _pos_1based(node: Node) -> tuple[int, int]:
    return node.start_point.row + 1, node.start_point.column + 1


def _normalize_under(root: Path, path: Path) -> str:
    return str(path.resolve().relative_to(root.resolve()))


def _extract_ts_string(n: Node) -> str | None:
    if n.type != "string":
        return None
    parts: list[str] = []
    for ch in n.children:
        if ch.type == "string_fragment":
            parts.append(ch.text.decode(errors="replace"))
    return "".join(parts)


def _ts_collect_module_specs(root_node: Node) -> list[tuple[str, int, int]]:
    """Return (spec text, line, col) for static import/export sources."""
    out: list[tuple[str, int, int]] = []

    def walk(n: Node) -> None:
        t = n.type
        if t in ("import_statement", "export_statement"):
            children = list(n.children)
            for i, ch in enumerate(children):
                if ch.type == "from" and i + 1 < len(children):
                    nxt = children[i + 1]
                    if nxt.type == "string":
                        frag = _extract_ts_string(nxt)
                        if frag is not None:
                            line, col = _pos_1based(nxt)
                            out.append((frag, line, col))
            if t == "import_statement" and len(children) >= 2:
                second = children[1]
                if second.type == "string":
                    frag = _extract_ts_string(second)
                    if frag is not None:
                        line, col = _pos_1based(second)
                        out.append((frag, line, col))
        elif t == "call_expression":
            fn = n.child_by_field_name("function")
            if fn is not None and fn.type == "import":
                args = n.child_by_field_name("arguments")
                if args is not None:
                    for ch in args.children:
                        if ch.type == "string":
                            frag = _extract_ts_string(ch)
                            if frag is not None:
                                line, col = _pos_1based(ch)
                                out.append((frag, line, col))
        for ch in n.children:
            walk(ch)

    walk(root_node)
    return out


def _resolve_ts_paths(
    source_file: Path,
    root: Path,
    specs: list[tuple[str, int, int]],
    known_relpaths: set[str],
) -> list[tuple[str, int, int, str]]:
    resolved: list[tuple[str, int, int, str]] = []
    src_dir = source_file.parent

    for spec, line, col in specs:
        spec = spec.strip()
        if not spec.startswith("."):
            continue

        cand_base = (src_dir / Path(spec)).resolve()
        candidates = [
            cand_base,
            cand_base.with_suffix(".ts"),
            cand_base.with_suffix(".tsx"),
            cand_base.with_suffix(".js"),
            cand_base.with_suffix(".jsx"),
            cand_base / "index.ts",
            cand_base / "index.tsx",
            cand_base / "index.js",
        ]
        hit: Path | None = None
        for c in candidates:
            try:
                cr = c.resolve()
                rel = _normalize_under(root, cr)
                if rel in known_relpaths:
                    hit = cr
                    break
            except ValueError:
                continue
        if hit is not None:
            resolved.append((_normalize_under(root, hit), line, col, spec))

    return resolved


def _rust_segments_from_scoped(node: Node) -> list[str]:
    if node.type == "identifier":
        return [node.text.decode(errors="replace")]
    if node.type == "crate":
        return ["crate"]
    if node.type == "super":
        return ["super"]
    if node.type == "self":
        return ["self"]
    if node.type == "scoped_identifier":
        parts: list[str] = []
        for ch in node.children:
            if ch.type == "::":
                continue
            parts.extend(_rust_segments_from_scoped(ch))
        return parts
    return []


def _rust_use_declaration_paths(node: Node) -> list[list[str]]:
    paths: list[list[str]] = []
    if node.type != "use_declaration":
        return paths
    for ch in node.children:
        if ch.type == "scoped_identifier":
            paths.append(_rust_segments_from_scoped(ch))
        elif ch.type == "use_list":
            for inner in ch.children:
                if inner.type == "scoped_identifier":
                    paths.append(_rust_segments_from_scoped(inner))
    return paths


def _rust_src_root(project_root: Path) -> Path:
    src = project_root / "src"
    return src if src.is_dir() else project_root


def _resolve_rust_crate_use(project_root: Path, segments: list[str]) -> Path | None:
    if not segments or segments[0] != "crate":
        return None
    body = segments[1:]
    if not body:
        return None
    src_root = _rust_src_root(project_root)
    for end in range(len(body), 0, -1):
        prefix = body[:end]
        dirs = prefix[:-1]
        name = prefix[-1]
        base = src_root.joinpath(*dirs) if dirs else src_root
        for cand in (base / f"{name}.rs", base / name / "mod.rs"):
            if cand.is_file():
                return cand.resolve()
    return None


def _resolve_rust_super_use(current_file: Path, segments: list[str]) -> Path | None:
    if not segments or segments[0] != "super":
        return None
    k = 0
    while k < len(segments) and segments[k] == "super":
        k += 1
    rest = segments[k:]
    if not rest:
        return None
    ancestor = current_file.parent
    for _ in range(max(0, k - 1)):
        ancestor = ancestor.parent
    dirs = rest[:-1]
    name = rest[-1]
    base = ancestor.joinpath(*dirs) if dirs else ancestor
    for cand in (base / f"{name}.rs", base / name / "mod.rs"):
        if cand.is_file():
            try:
                return cand.resolve()
            except OSError:
                continue
    return None


def _collect_rust_edges(
    source_file: Path,
    project_root: Path,
    known_relpaths: set[str],
) -> list[tuple[str, int, int, str]]:
    parser = PARSERS["rust"]
    tree = parser.parse(source_file.read_bytes())
    edges: list[tuple[str, int, int, str]] = []

    def walk(n: Node) -> None:
        if n.type == "use_declaration":
            for segs in _rust_use_declaration_paths(n):
                if not segs:
                    continue
                line, col = _pos_1based(n)
                reason = "::".join(segs)
                target: Path | None = None
                if segs[0] == "crate":
                    target = _resolve_rust_crate_use(project_root, segs)
                elif segs[0] == "super":
                    target = _resolve_rust_super_use(source_file, segs)
                elif segs[0] not in ("std", "core", "alloc"):
                    target = _resolve_rust_crate_use(project_root, ["crate", *segs])
                if target is not None:
                    try:
                        rel = _normalize_under(project_root, target)
                        if rel in known_relpaths:
                            edges.append((rel, line, col, reason))
                    except ValueError:
                        pass
        elif n.type == "mod_item":
            body = [c for c in n.children if c.type == "declaration_list"]
            if body:
                for ch in n.children:
                    walk(ch)
                return
            ident = n.child_by_field_name("name")
            if ident is None:
                for ch in n.children:
                    if ch.type == "identifier":
                        ident = ch
                        break
            if ident is not None:
                name = ident.text.decode(errors="replace")
                line, col = _pos_1based(ident)
                base_dir = source_file.parent
                for cand in (base_dir / f"{name}.rs", base_dir / name / "mod.rs"):
                    if cand.is_file():
                        try:
                            tgt = cand.resolve()
                            rel = _normalize_under(project_root, tgt)
                            if rel in known_relpaths:
                                edges.append((rel, line, col, f"mod {name}"))
                        except ValueError:
                            pass
        for ch in n.children:
            walk(ch)

    walk(tree.root_node)
    return edges


def _kotlin_import_paths(root_node: Node) -> list[tuple[str, int, int]]:
    out: list[tuple[str, int, int]] = []

    def walk(n: Node) -> None:
        if n.type == "import":
            for ch in n.children:
                if ch.type == "qualified_identifier":
                    qtext = ch.text.decode(errors="replace").strip()
                    line, col = _pos_1based(ch)
                    out.append((qtext, line, col))
        for ch in n.children:
            walk(ch)

    walk(root_node)
    return out


def _resolve_kotlin_import(project_root: Path, qname: str, known_relpaths: set[str]) -> str | None:
    parts = qname.split(".")
    if len(parts) < 2:
        return None
    tail_path = Path(*parts[:-1]) / f"{parts[-1]}.kt"
    tail_posix = tail_path.as_posix().replace("\\", "/")
    for rel in known_relpaths:
        rp = rel.replace("\\", "/")
        if rp.endswith(tail_posix):
            return rel
    tail_kts = (Path(*parts[:-1]) / f"{parts[-1]}.kts").as_posix().replace("\\", "/")
    for rel in known_relpaths:
        rp = rel.replace("\\", "/")
        if rp.endswith(tail_kts):
            return rel
    return None


def _collect_kotlin_edges(
    source_file: Path,
    project_root: Path,
    known_relpaths: set[str],
) -> list[tuple[str, int, int, str]]:
    parser = PARSERS["kotlin"]
    tree = parser.parse(source_file.read_bytes())
    edges: list[tuple[str, int, int, str]] = []
    skip_prefixes = ("java.", "javax.", "kotlin.", "kotlinx.", "android.")
    for qname, line, col in _kotlin_import_paths(tree.root_node):
        if any(qname.startswith(p) for p in skip_prefixes):
            continue
        hit = _resolve_kotlin_import(project_root, qname, known_relpaths)
        if hit:
            edges.append((hit, line, col, qname))
    return edges


def _collect_ts_edges_file(
    source_file: Path,
    project_root: Path,
    lang: str,
    known_relpaths: set[str],
) -> list[tuple[str, int, int, str]]:
    parser = PARSERS[lang]
    tree = parser.parse(source_file.read_bytes())
    specs = _ts_collect_module_specs(tree.root_node)
    resolved = _resolve_ts_paths(source_file, project_root, specs, known_relpaths)
    return [(t, ln, c, f"`{rs}`") for t, ln, c, rs in resolved]


def _edges_for_file(
    path: Path,
    lang: str,
    project_root: Path,
    known_relpaths: set[str],
) -> list[tuple[str, int, int, str]]:
    if lang == "rust":
        return _collect_rust_edges(path, project_root, known_relpaths)
    if lang == "kotlin":
        return _collect_kotlin_edges(path, project_root, known_relpaths)
    if lang in ("ts", "tsx"):
        return _collect_ts_edges_file(path, project_root, lang, known_relpaths)
    return []


@dataclass
class CouplingProjectResult:
    root: Path
    files_count: int
    internal_edge_count: int
    average_fan_in: float
    average_fan_out: float
    ratio_of_average_fan_in_to_fan_out: float | None
    average_file_fan_in_fan_out_ratio: float | None
    files_with_fan_out_zero: int
    files_with_parse_or_io_errors: list[tuple[str, str]] = field(default_factory=list)
    debug_steps: list[ComputationStep] | None = None

    def summary_text(self) -> str:
        r_avg = self.ratio_of_average_fan_in_to_fan_out
        r_avg_s = f"{r_avg:.4f}" if r_avg is not None else "n/a"
        r_file = self.average_file_fan_in_fan_out_ratio
        r_file_s = f"{r_file:.4f}" if r_file is not None else "n/a"
        return (
            "Coupling (file-level internal dependencies)\n"
            f"  Files analyzed: {self.files_count}\n"
            f"  Resolved internal edges (distinct ordered pairs): {self.internal_edge_count}\n"
            f"  Average fan-in:  {self.average_fan_in:.4f}\n"
            f"  Average fan-out: {self.average_fan_out:.4f}\n"
            f"  Ratio (avg fan-in / avg fan-out): {r_avg_s}\n"
            f"  Average per-file ratio (mean of fan_in/fan_out over files with fan-out > 0): {r_file_s}\n"
            f"  Files with fan-out 0: {self.files_with_fan_out_zero}"
        )

    def debug_text(self) -> str:
        from software_metrics.debug_report import format_computation_steps

        if not self.debug_steps:
            return ""
        return format_computation_steps(
            COUPLING_METRIC_ID,
            self.debug_steps,
            header=f"Project root: {self.root}",
        )


def analyze_coupling_project(root: Path, *, debug: bool = False) -> CouplingProjectResult:
    root = root.resolve()
    files_meta = iter_metric_files(root)
    known_relpaths: set[str] = set()
    resolved_paths: list[tuple[Path, str]] = []
    errors: list[tuple[str, str]] = []

    for path, lang in files_meta:
        try:
            rp = path.resolve()
            rel = _normalize_under(root, rp)
            known_relpaths.add(rel)
            resolved_paths.append((rp, lang))
        except (OSError, ValueError) as e:
            errors.append((str(path), str(e)))

    # fan-out / fan-in counts per file (relative path keys)
    fan_out: dict[str, set[str]] = defaultdict(set)
    fan_in: dict[str, set[str]] = defaultdict(set)
    edge_records: dict[tuple[str, str], tuple[int, int, str]] = {}

    for path, lang in resolved_paths:
        rel_from = _normalize_under(root, path)
        try:
            raw_edges = _edges_for_file(path, lang, root, known_relpaths)
        except OSError as e:
            errors.append((str(path), str(e)))
            continue
        for to_rel, ln, col, detail in raw_edges:
            if to_rel == rel_from:
                continue
            key = (rel_from, to_rel)
            fan_out[rel_from].add(to_rel)
            fan_in[to_rel].add(rel_from)
            if key not in edge_records:
                edge_records[key] = (ln, col, detail)

    n_files = len(known_relpaths)
    total_fan_in = sum(len(fan_in[f]) for f in known_relpaths)
    total_fan_out = sum(len(fan_out[f]) for f in known_relpaths)

    avg_in = total_fan_in / n_files if n_files else 0.0
    avg_out = total_fan_out / n_files if n_files else 0.0
    ratio_avgs = (avg_in / avg_out) if avg_out > 0 else None

    ratios: list[float] = []
    fan_out_zero = 0
    for f in known_relpaths:
        fo = len(fan_out[f])
        fi = len(fan_in[f])
        if fo == 0:
            fan_out_zero += 1
        else:
            ratios.append(fi / fo)

    avg_file_ratio = sum(ratios) / len(ratios) if ratios else None

    debug_steps: list[ComputationStep] | None = [] if debug else None
    if debug and debug_steps is not None:
        for (src, tgt), (ln, col, detail) in sorted(edge_records.items()):
            src_path = (root / Path(src)).resolve()
            debug_steps.append(
                ComputationStep(
                    COUPLING_METRIC_ID,
                    str(src_path),
                    "dependency edge",
                    ln,
                    col,
                    "resolved_import",
                    1,
                    f"→ {tgt} ({detail})",
                )
            )

    return CouplingProjectResult(
        root=root,
        files_count=n_files,
        internal_edge_count=len(edge_records),
        average_fan_in=avg_in,
        average_fan_out=avg_out,
        ratio_of_average_fan_in_to_fan_out=ratio_avgs,
        average_file_fan_in_fan_out_ratio=avg_file_ratio,
        files_with_fan_out_zero=fan_out_zero,
        files_with_parse_or_io_errors=errors,
        debug_steps=debug_steps if debug else None,
    )
