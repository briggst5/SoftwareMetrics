"""
Average McCabe cyclomatic complexity per function/method.

Uses a standard *approximation* aligned with common static analyzers: start at 1 for
each function, then add one for each decision point in the control-flow structure
(if, loops, match/switch/when arms, catch, && / ||, ternary). Nested functions are
scored separately; their bodies are not folded into the outer score.

Note: ordinary function *calls* are not decision points and are not counted.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from tree_sitter import Language, Node, Parser

from software_metrics.debug_report import ComputationStep, format_computation_steps

import tree_sitter_kotlin as tsk
import tree_sitter_rust as tsr
import tree_sitter_typescript as tst

SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        ".svn",
        ".hg",
        "node_modules",
        "target",
        "dist",
        "build",
        ".gradle",
        ".venv",
        "__pycache__",
        ".idea",
        ".turbo",
        ".next",
        "venv",
    },
)

EXTENSION_LANG: dict[str, str] = {
    ".rs": "rust",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".ts": "ts",
    ".tsx": "tsx",
}


def _language_parsers() -> dict[str, Parser]:
    rust = Language(tsr.language())
    kotlin = Language(tsk.language())
    ts = Language(tst.language_typescript())
    tsx = Language(tst.language_tsx())
    return {
        "rust": Parser(rust),
        "kotlin": Parser(kotlin),
        "ts": Parser(ts),
        "tsx": Parser(tsx),
    }


PARSERS = _language_parsers()

CYCLOMATIC_METRIC_ID = "cyclomatic-complexity"

# Node types treated as separate functions for per-unit metrics.
FUNCTION_KINDS: dict[str, frozenset[str]] = {
    "rust": frozenset({"function_item"}),
    "kotlin": frozenset({"function_declaration"}),
    "ts": frozenset({"function_declaration", "method_definition", "arrow_function"}),
    "tsx": frozenset({"function_declaration", "method_definition", "arrow_function"}),
}


def _is_logical_binary(node: Node) -> bool:
    if node.type != "binary_expression":
        return False
    return any(ch.type in ("&&", "||") for ch in node.children)


def _rust_match_arms(match_expr: Node) -> int:
    for ch in match_expr.children:
        if ch.type == "match_block":
            return sum(1 for c in ch.children if c.type == "match_arm")
    return 0


def _ts_switch_branches(sw: Node) -> int:
    for ch in sw.children:
        if ch.type == "switch_body":
            n = 0
            for c in ch.children:
                if c.type == "switch_case":
                    n += 1
                elif c.type == "switch_default":
                    n += 1
            return n
    return 0


def _kotlin_when_entries(when_expr: Node) -> int:
    return sum(1 for c in when_expr.children if c.type == "when_entry")


def _node_location_1based(node: Node) -> tuple[int, int]:
    """Human-readable line (1-based) and column (1-based)."""
    return node.start_point.row + 1, node.start_point.column + 1


def _decision_weight(node: Node, lang: str) -> int:
    t = node.type

    if lang == "rust":
        if t in (
            "if_expression",
            "while_expression",
            "for_expression",
            "loop_expression",
        ):
            return 1
        if t == "match_expression":
            return _rust_match_arms(node)
        if t == "binary_expression" and _is_logical_binary(node):
            return 1
        return 0

    if lang == "kotlin":
        if t in ("if_expression", "while_statement", "for_statement", "do_while_statement"):
            return 1
        if t == "when_expression":
            return _kotlin_when_entries(node)
        if t == "try_expression":
            return sum(1 for c in node.children if c.type == "catch_block")
        if t == "binary_expression" and _is_logical_binary(node):
            return 1
        return 0

    if lang in ("ts", "tsx"):
        if t in (
            "if_statement",
            "while_statement",
            "for_statement",
            "for_in_statement",
            "for_of_statement",
            "do_statement",
        ):
            return 1
        if t == "switch_statement":
            return _ts_switch_branches(node)
        if t == "catch_clause":
            return 1
        if t == "ternary_expression":
            return 1
        if t == "binary_expression" and _is_logical_binary(node):
            return 1
        return 0

    return 0


def _decision_reason(node: Node, lang: str, weight: int) -> str:
    """Human-readable rationale for a non-zero decision weight."""
    t = node.type
    if lang == "rust":
        if t == "match_expression":
            return f"match expression with {_rust_match_arms(node)} arm(s)"
        if t == "binary_expression":
            return "boolean short-circuit via && or ||"
        return {
            "if_expression": "if expression adds a branch",
            "while_expression": "while loop",
            "for_expression": "for loop",
            "loop_expression": "loop",
        }.get(t, f"decision node ({t})")

    if lang == "kotlin":
        if t == "when_expression":
            return f"when expression with {_kotlin_when_entries(node)} entr(y/ies)"
        if t == "try_expression":
            ncatches = sum(1 for c in node.children if c.type == "catch_block")
            return f"try with {ncatches} catch block(s)"
        if t == "binary_expression":
            return "boolean short-circuit via && or ||"
        return {
            "if_expression": "if expression adds a branch",
            "while_statement": "while loop",
            "for_statement": "for loop",
            "do_while_statement": "do-while loop",
        }.get(t, f"decision node ({t})")

    if lang in ("ts", "tsx"):
        if t == "switch_statement":
            return f"switch with {_ts_switch_branches(node)} branch(es) (cases/default)"
        if t == "binary_expression":
            return "boolean short-circuit via && or ||"
        return {
            "if_statement": "if statement adds a branch",
            "while_statement": "while loop",
            "for_statement": "for loop",
            "for_in_statement": "for-in loop",
            "for_of_statement": "for-of loop",
            "do_statement": "do-while loop",
            "catch_clause": "catch clause",
            "ternary_expression": "ternary conditional",
        }.get(t, f"decision node ({t})")

    return f"decision node ({t}, weight={weight})"


def _function_unit_label(fn_node: Node, lang: str) -> str:
    name_node = fn_node.child_by_field_name("name")
    if name_node is not None and name_node.text:
        return name_node.text.decode(errors="replace")
    if fn_node.type == "arrow_function":
        return "<anonymous arrow>"
    return fn_node.type


def _walk_cyclomatic(
    root_fn: Node,
    lang: str,
    *,
    path_str: str,
    unit_label: str,
    steps_out: list[ComputationStep] | None,
) -> int:
    kinds = FUNCTION_KINDS[lang]
    decisions = 0

    def is_nested_function(n: Node) -> bool:
        return n is not root_fn and n.type in kinds

    if steps_out is not None:
        line, col = _node_location_1based(root_fn)
        steps_out.append(
            ComputationStep(
                CYCLOMATIC_METRIC_ID,
                path_str,
                unit_label,
                line,
                col,
                "(base)",
                1,
                "McCabe cyclomatic base (one linear path baseline)",
            )
        )

    def visit(n: Node) -> None:
        nonlocal decisions
        if is_nested_function(n):
            return
        w = _decision_weight(n, lang)
        if w:
            decisions += w
            if steps_out is not None:
                line, col = _node_location_1based(n)
                reason = _decision_reason(n, lang, w)
                steps_out.append(
                    ComputationStep(
                        CYCLOMATIC_METRIC_ID,
                        path_str,
                        unit_label,
                        line,
                        col,
                        n.type,
                        w,
                        reason,
                    )
                )
        for ch in n.children:
            visit(ch)

    visit(root_fn)
    return 1 + decisions


def cyclomatic_for_function(root_fn: Node, lang: str) -> int:
    return _walk_cyclomatic(
        root_fn,
        lang,
        path_str="",
        unit_label="",
        steps_out=None,
    )


def _collect_functions(root: Node, lang: str) -> list[Node]:
    kinds = FUNCTION_KINDS[lang]
    out: list[Node] = []

    def walk(n: Node) -> None:
        if n.type in kinds:
            out.append(n)
        for ch in n.children:
            walk(ch)

    walk(root)
    return out


def analyze_source_bytes(source: bytes, lang: str) -> tuple[list[int], str | None]:
    """
    Compute cyclomatic complexity for each function-like unit in ``source``.

    ``lang`` must be one of: ``rust``, ``kotlin``, ``ts``, ``tsx``.
    Returns ``([], error)`` when the parse tree has errors.
    """
    complexities, err, _ = analyze_source_bytes_detailed(
        source,
        lang,
        path_display="<memory>",
        debug=False,
    )
    return complexities, err


def analyze_source_bytes_detailed(
    source: bytes,
    lang: str,
    path_display: str,
    *,
    debug: bool,
) -> tuple[list[int], str | None, list[ComputationStep]]:
    """Like :func:`analyze_source_bytes` but can attach per-unit computation traces."""
    parser = PARSERS[lang]
    tree = parser.parse(source)
    if tree.root_node.has_error:
        return [], "parse tree has errors (skipped)", []
    complexities: list[int] = []
    steps: list[ComputationStep] = []
    for fn in _collect_functions(tree.root_node, lang):
        label = _function_unit_label(fn, lang)
        unit_steps: list[ComputationStep] | None = [] if debug else None
        score = _walk_cyclomatic(
            fn,
            lang,
            path_str=path_display,
            unit_label=label,
            steps_out=unit_steps,
        )
        complexities.append(score)
        if debug and unit_steps is not None:
            steps.extend(unit_steps)
    return complexities, None, steps


def _analyze_source(
    path: Path,
    lang: str,
    *,
    debug: bool = False,
) -> tuple[list[int], str | None, list[ComputationStep]]:
    try:
        text = path.read_bytes()
    except OSError as e:
        return [], str(e), []
    return analyze_source_bytes_detailed(text, lang, str(path), debug=debug)


def iter_metric_files(root: Path) -> list[tuple[Path, str]]:
    files: list[tuple[Path, str]] = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES]
        base = Path(dirpath)
        for name in filenames:
            p = base / name
            ext = p.suffix.lower()
            lang = EXTENSION_LANG.get(ext)
            if lang:
                files.append((p, lang))
    return files


@dataclass
class CyclomaticProjectResult:
    root: Path
    method_count: int
    total_complexity: int
    average_complexity: float | None
    files_scanned: int
    files_with_errors: list[tuple[str, str]] = field(default_factory=list)
    debug_steps: list[ComputationStep] | None = None

    def summary_text(self) -> str:
        if self.method_count == 0:
            return (
                f"Project cyclomatic complexity (average per function): n/a\n"
                f"  (no functions found under {self.root})\n"
                f"  Files scanned: {self.files_scanned}"
            )
        avg = self.average_complexity
        assert avg is not None
        return (
            f"Project cyclomatic complexity (average per function): {avg:.4f}\n"
            f"  Functions/methods: {self.method_count}\n"
            f"  Sum of complexities: {self.total_complexity}\n"
            f"  Files scanned: {self.files_scanned}"
        )

    def debug_text(self) -> str:
        """Formatted trace for CLI when ``debug_steps`` was captured."""
        if not self.debug_steps:
            return ""
        return format_computation_steps(
            CYCLOMATIC_METRIC_ID,
            self.debug_steps,
            header=f"Project root: {self.root}",
        )


def analyze_cyclomatic_project(root: Path, *, debug: bool = False) -> CyclomaticProjectResult:
    total_c = 0
    n_methods = 0
    files_scanned = 0
    errors: list[tuple[str, str]] = []
    debug_steps: list[ComputationStep] | None = [] if debug else None

    for path, lang in iter_metric_files(root):
        complexities, err, file_steps = _analyze_source(path, lang, debug=debug)
        if err:
            errors.append((str(path), err))
            continue
        files_scanned += 1
        total_c += sum(complexities)
        n_methods += len(complexities)
        if debug and debug_steps is not None:
            debug_steps.extend(file_steps)

    avg: float | None
    if n_methods == 0:
        avg = None
    else:
        avg = total_c / n_methods

    return CyclomaticProjectResult(
        root=root,
        method_count=n_methods,
        total_complexity=total_c,
        average_complexity=avg,
        files_scanned=files_scanned,
        files_with_errors=errors,
        debug_steps=debug_steps if debug else None,
    )
