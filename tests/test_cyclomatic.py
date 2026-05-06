"""Unit tests for cyclomatic complexity aggregation and edge cases."""

from __future__ import annotations

from pathlib import Path

import pytest

from software_metrics.discovery import EXTENSION_LANG
from software_metrics.metrics.cyclomatic import (
    CyclomaticProjectResult,
    analyze_cyclomatic_project,
    analyze_source_bytes,
)


def test_fixtures_aggregate_matches_expected(fixtures_dir: Path) -> None:
    """Golden aggregate over tests/fixtures (Rust + TS + Kotlin samples)."""
    result = analyze_cyclomatic_project(fixtures_dir)
    assert result.method_count == 8
    assert result.total_complexity == 18
    assert result.average_complexity == pytest.approx(2.25)
    assert result.files_scanned == 3
    assert result.files_with_errors == []


def test_empty_directory_reports_no_methods(tmp_path: Path) -> None:
    result = analyze_cyclomatic_project(tmp_path)
    assert result.method_count == 0
    assert result.total_complexity == 0
    assert result.average_complexity is None
    assert result.files_scanned == 0
    assert result.files_with_errors == []
    assert "n/a" in result.summary_text()


@pytest.mark.parametrize(
    ("lang", "source", "expected_complexities"),
    [
        ("rust", "fn f() {}\n", [1]),
        ("rust", "fn f() { if true {} }\n", [2]),
        (
            "rust",
            "fn outer() {\n    fn inner() { if true {} }\n}\n",
            [1, 2],
        ),
        ("ts", "function f() {}\n", [1]),
        ("ts", "function f() { if (true) {} }\n", [2]),
        ("kotlin", "fun f() {}\n", [1]),
        ("kotlin", "fun f() { if (true) {} }\n", [2]),
    ],
)
def test_inline_source_complexities(
    lang: str,
    source: str,
    expected_complexities: list[int],
) -> None:
    """Per-function scores for small synthetic snippets (AST preorder)."""
    complexities, err = analyze_source_bytes(source.encode("utf-8"), lang)
    assert err is None
    assert complexities == expected_complexities


def test_nested_rust_functions_scored_separately() -> None:
    """Inner function body must not inflate outer cyclomatic score."""
    src = (
        b"fn outer() {\n"
        b"    fn inner() {\n"
        b"        if true {}\n"
        b"    }\n"
        b"}\n"
    )
    complexities, err = analyze_source_bytes(src, "rust")
    assert err is None
    assert complexities == [1, 2]


def test_skipped_directory_not_walked(tmp_path: Path) -> None:
    nm = tmp_path / "node_modules"
    nm.mkdir()
    nm.joinpath("hidden.rs").write_text("fn hidden() {}\n", encoding="utf-8")
    result = analyze_cyclomatic_project(tmp_path)
    assert result.method_count == 0
    assert result.files_scanned == 0


def test_unparseable_source_recorded_as_error(tmp_path: Path) -> None:
    tmp_path.joinpath("broken.rs").write_text("fn broken() {", encoding="utf-8")
    result = analyze_cyclomatic_project(tmp_path)
    assert result.method_count == 0
    assert result.files_scanned == 0
    assert len(result.files_with_errors) == 1
    assert "broken.rs" in result.files_with_errors[0][0]
    assert "parse" in result.files_with_errors[0][1].lower()


def test_analyze_source_bytes_returns_error_for_invalid_parse() -> None:
    complexities, err = analyze_source_bytes(b"fn broken() {", "rust")
    assert complexities == []
    assert err is not None
    assert "parse" in err.lower()


def test_extension_lang_maps_ts_and_tsx() -> None:
    assert EXTENSION_LANG[".ts"] == "ts"
    assert EXTENSION_LANG[".tsx"] == "tsx"


def test_summary_text_with_methods() -> None:
    r = CyclomaticProjectResult(
        root=Path("/proj"),
        method_count=3,
        total_complexity=9,
        average_complexity=3.0,
        files_scanned=2,
    )
    text = r.summary_text()
    assert "3.0000" in text
    assert "Functions/methods: 3" in text
    assert "Sum of complexities: 9" in text
