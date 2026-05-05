"""
Extensive cyclomatic complexity corner-case coverage.

Several semantics are intentional but subtle:

- **Rust** closures are not separate units; decisions inside a closure still increase the
  enclosing function's score.
- **Kotlin** lambdas behave like Rust closures for scoring.
- **TypeScript / TSX** ``arrow_function`` nodes are separate units (including nested
  arrows), so nested arrows split complexity across functions.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from software_metrics.metrics.cyclomatic import (
    SKIP_DIR_NAMES,
    analyze_cyclomatic_project,
    analyze_source_bytes,
    iter_metric_files,
)


# --- Rust: decision constructs -------------------------------------------------

_RUST_SNIPPETS: list[tuple[str, str, list[int]]] = [
    ("trivial", "fn f() {}\n", [1]),
    ("if", "fn f() { if true {} }\n", [2]),
    ("while", "fn f() { while true {} }\n", [2]),
    ("for", "fn f() { for _ in 0..1 {} }\n", [2]),
    ("loop", "fn f() { loop {} }\n", [2]),
    (
        "match_single_arm",
        "fn f() { match x { A => {} } }\n",
        [2],
    ),
    (
        "match_three_arms",
        "fn f() {\n  match x {\n    A => {},\n    B => {},\n    _ => {},\n  }\n}\n",
        [4],
    ),
    (
        "logical_and_or",
        "fn f() { let _ = a && b || c; }\n",
        [3],
    ),
    (
        "impl_method",
        "struct S;\nimpl S {\n  fn m(&self) {}\n}\n",
        [1],
    ),
    (
        "nested_named_functions",
        "fn outer() {\n  fn inner() { if true {} }\n}\n",
        [1, 2],
    ),
    (
        "unicode_identifier",
        "fn 你好() {}\n",
        [1],
    ),
]


@pytest.mark.parametrize(
    ("_name", "source", "expected"),
    _RUST_SNIPPETS,
    ids=[t[0] for t in _RUST_SNIPPETS],
)
def test_rust_snippets_decisions(_name: str, source: str, expected: list[int]) -> None:
    complexities, err = analyze_source_bytes(source.encode("utf-8"), "rust")
    assert err is None
    assert complexities == expected


def test_rust_closure_body_counts_toward_enclosing_function() -> None:
    """Closure is not a scored unit; inner ``if`` increases ``f`` only."""
    src = (
        "fn f() {\n"
        "  let _ = || {\n"
        "    if true {}\n"
        "  };\n"
        "}\n"
    )
    complexities, err = analyze_source_bytes(src.encode("utf-8"), "rust")
    assert err is None
    assert complexities == [2]


# --- Kotlin -------------------------------------------------------------------


_KOTLIN_SNIPPETS: list[tuple[str, str, list[int]]] = [
    ("trivial", "fun f() {}\n", [1]),
    ("if", "fun f() { if (true) {} }\n", [2]),
    ("while", "fun f() { while (true) {} }\n", [2]),
    ("for", "fun f() { for (i in 1..2) {} }\n", [2]),
    ("do_while", "fun f() { do { } while (true) }\n", [2]),
    (
        "when_three_entries",
        "fun f() {\n  when (x) {\n    1 -> {}\n    2 -> {}\n    else -> {}\n  }\n}\n",
        [4],
    ),
    (
        "try_two_catches",
        "fun f() {\n"
        "    try {\n"
        "    } catch (e: Exception) {\n"
        "    } catch (e: Error) {\n"
        "    }\n"
        "}\n",
        [3],
    ),
    (
        "nested_named_functions",
        "fun outer() {\n  fun inner() { if (true) {} }\n}\n",
        [1, 2],
    ),
]


@pytest.mark.parametrize(
    ("_name", "source", "expected"),
    _KOTLIN_SNIPPETS,
    ids=[t[0] for t in _KOTLIN_SNIPPETS],
)
def test_kotlin_snippets_decisions(_name: str, source: str, expected: list[int]) -> None:
    complexities, err = analyze_source_bytes(source.encode("utf-8"), "kotlin")
    assert err is None
    assert complexities == expected


def test_kotlin_lambda_body_counts_toward_outer_function() -> None:
    """Anonymous lambdas are not separate units like nested ``fun`` declarations."""
    src = (
        "fun outer() {\n"
        "  val x = { if (true) {} }\n"
        "}\n"
    )
    complexities, err = analyze_source_bytes(src.encode("utf-8"), "kotlin")
    assert err is None
    assert complexities == [2]


# --- TypeScript ---------------------------------------------------------------


_TS_SNIPPETS: list[tuple[str, str, list[int]]] = [
    ("trivial", "function f() {}\n", [1]),
    ("if", "function f() { if (true) {} }\n", [2]),
    ("while", "function f() { while (true) {} }\n", [2]),
    ("for_classic", "function f() { for (;;) {} }\n", [2]),
    ("for_of", "function f() { for (const x of y) {} }\n", [2]),
    ("for_in", "function f() { for (const k in o) {} }\n", [2]),
    ("do_while", "function f() { do {} while (x); }\n", [2]),
    (
        "switch_case_and_default",
        "function f() {\n"
        "  switch (x) {\n"
        "    case 1: break;\n"
        "    default: break;\n"
        "  }\n"
        "}\n",
        [3],
    ),
    ("try_catch", "function f() { try {} catch (e) {} }\n", [2]),
    ("ternary", "function f() { return a ? b : c; }\n", [2]),
    (
        "logical_chain",
        "function f() { return a && b || c; }\n",
        [3],
    ),
    (
        "else_if_chain",
        "function f() {\n"
        "  if (a) {}\n"
        "  else if (b) {}\n"
        "  else {}\n"
        "}\n",
        [3],
    ),
    (
        "class_method",
        "class C {\n  m() { return 1; }\n}\n",
        [1],
    ),
    (
        "nested_function_declaration",
        "function outer() {\n  function inner() { if (true) {} }\n}\n",
        [1, 2],
    ),
    (
        "outer_and_arrow_nested",
        "function outer() {\n"
        "  const inner = () => { if (true) {} };\n"
        "}\n",
        [1, 2],
    ),
    (
        "exported_arrow",
        "export const X = () => { if (x) {} };\n",
        [2],
    ),
]


@pytest.mark.parametrize(
    ("_name", "source", "expected"),
    _TS_SNIPPETS,
    ids=[t[0] for t in _TS_SNIPPETS],
)
def test_typescript_snippets_decisions(_name: str, source: str, expected: list[int]) -> None:
    complexities, err = analyze_source_bytes(source.encode("utf-8"), "ts")
    assert err is None
    assert complexities == expected


# --- TSX ----------------------------------------------------------------------


def test_tsx_function_and_nested_arrow_in_jsx() -> None:
    """Preorder: outer component then nested arrow inside JSX."""
    src = """export function Page() {
  if (loading) return null;
  return <Box>{items.map(x => x)}</Box>;
}
"""
    complexities, err = analyze_source_bytes(src.encode("utf-8"), "tsx")
    assert err is None
    assert complexities == [2, 1]


def test_tsx_parses_fragment_and_basic_component() -> None:
    src = "export function C(){ return <></>; }\n"
    complexities, err = analyze_source_bytes(src.encode("utf-8"), "tsx")
    assert err is None
    assert complexities == [1]


# --- Empty / parse failures ---------------------------------------------------


@pytest.mark.parametrize("lang", ["rust", "kotlin", "ts", "tsx"])
def test_empty_source_has_no_functions(lang: str) -> None:
    complexities, err = analyze_source_bytes(b"", lang)
    assert err is None
    assert complexities == []


@pytest.mark.parametrize(
    ("lang", "broken"),
    [
        ("rust", b"fn x() {"),
        ("kotlin", b"fun x() {"),
        ("ts", b"function x() {"),
        ("tsx", b"function x() {"),
    ],
)
def test_broken_parse_returns_error(lang: str, broken: bytes) -> None:
    complexities, err = analyze_source_bytes(broken, lang)
    assert complexities == []
    assert err is not None


# --- Filesystem walking -------------------------------------------------------


@pytest.mark.parametrize(
    "dirname",
    sorted(SKIP_DIR_NAMES),
)
def test_iter_metric_files_skips_named_directories(tmp_path: Path, dirname: str) -> None:
    bad = tmp_path / dirname
    bad.mkdir(parents=True)
    bad.joinpath("hide.rs").write_text("fn hide() {}\n", encoding="utf-8")
    found = iter_metric_files(tmp_path)
    assert found == []


def test_iter_metric_files_finds_nested_sources(tmp_path: Path) -> None:
    src = tmp_path / "src" / "deep"
    src.mkdir(parents=True)
    src.joinpath("m.rs").write_text("fn m() {}\n", encoding="utf-8")
    found = iter_metric_files(tmp_path)
    assert len(found) == 1
    assert found[0][0].name == "m.rs"
    assert found[0][1] == "rust"


def test_iter_metric_files_ignores_unknown_extensions(tmp_path: Path) -> None:
    tmp_path.joinpath("readme.txt").write_text("hello", encoding="utf-8")
    tmp_path.joinpath("data.json").write_text("{}", encoding="utf-8")
    assert iter_metric_files(tmp_path) == []


def test_iter_metric_files_maps_extensions(tmp_path: Path) -> None:
    tmp_path.joinpath("a.rs").write_text("fn a(){}\n", encoding="utf-8")
    tmp_path.joinpath("b.kt").write_text("fun b(){}\n", encoding="utf-8")
    tmp_path.joinpath("c.kts").write_text("fun c(){}\n", encoding="utf-8")
    tmp_path.joinpath("d.ts").write_text("function d(){}\n", encoding="utf-8")
    tmp_path.joinpath("e.tsx").write_text("export function e(){}\n", encoding="utf-8")
    found = {p.name: lang for p, lang in iter_metric_files(tmp_path)}
    assert found["a.rs"] == "rust"
    assert found["b.kt"] == "kotlin"
    assert found["c.kts"] == "kotlin"
    assert found["d.ts"] == "ts"
    assert found["e.tsx"] == "tsx"


def test_iter_metric_files_survives_empty_directory(tmp_path: Path) -> None:
    assert iter_metric_files(tmp_path) == []


def test_iter_metric_files_collects_multiple_nested_files(tmp_path: Path) -> None:
    (tmp_path / "pkg" / "a").mkdir(parents=True)
    (tmp_path / "pkg" / "b").mkdir(parents=True)
    (tmp_path / "pkg" / "a").joinpath("one.rs").write_text("fn one(){}\n", encoding="utf-8")
    (tmp_path / "pkg" / "b").joinpath("two.rs").write_text("fn two(){}\n", encoding="utf-8")
    names = sorted(p.name for p, _ in iter_metric_files(tmp_path))
    assert names == ["one.rs", "two.rs"]


# --- Project aggregation ------------------------------------------------------


def test_project_aggregates_multiple_files(tmp_path: Path) -> None:
    tmp_path.joinpath("a.rs").write_text("fn a(){}\n", encoding="utf-8")
    tmp_path.joinpath("b.rs").write_text("fn b(){ if true {} }\n", encoding="utf-8")
    result = analyze_cyclomatic_project(tmp_path)
    assert result.files_scanned == 2
    assert result.method_count == 2
    assert result.total_complexity == 3
    assert result.average_complexity == pytest.approx(1.5)
    assert result.files_with_errors == []


def test_project_counts_only_successful_files_when_one_parse_fails(tmp_path: Path) -> None:
    tmp_path.joinpath("good.rs").write_text("fn ok(){}\n", encoding="utf-8")
    tmp_path.joinpath("bad.rs").write_text("fn bad() {", encoding="utf-8")
    result = analyze_cyclomatic_project(tmp_path)
    assert result.files_scanned == 1
    assert result.method_count == 1
    assert result.total_complexity == 1
    assert len(result.files_with_errors) == 1


def test_project_skips_nested_vendor_but_keeps_sibling_sources(tmp_path: Path) -> None:
    tmp_path.joinpath("lib.rs").write_text("fn lib(){}\n", encoding="utf-8")
    nm = tmp_path / "node_modules"
    nm.mkdir()
    nm.joinpath("pkg.rs").write_text("fn pkg(){}\n", encoding="utf-8")
    result = analyze_cyclomatic_project(tmp_path)
    assert result.files_scanned == 1
    assert result.method_count == 1


@pytest.mark.parametrize(
    "skip_root_name",
    ["target", "build", "dist", ".gradle"],
)
def test_project_skips_common_build_roots(tmp_path: Path, skip_root_name: str) -> None:
    root = tmp_path / skip_root_name
    root.mkdir()
    root.joinpath("inside.rs").write_text("fn inside(){}\n", encoding="utf-8")
    result = analyze_cyclomatic_project(tmp_path)
    assert result.method_count == 0


# --- Result formatting --------------------------------------------------------


def test_summary_text_no_methods_shows_na_and_root(tmp_path: Path) -> None:
    result = analyze_cyclomatic_project(tmp_path)
    text = result.summary_text()
    assert "n/a" in text
    assert str(tmp_path.resolve()) in text or str(tmp_path) in text
