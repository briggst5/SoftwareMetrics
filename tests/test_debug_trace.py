"""Debug trace format and cyclomatic detailed analysis."""

from __future__ import annotations

from pathlib import Path

import pytest

from software_metrics.debug_report import ComputationStep, format_computation_steps
from software_metrics.metrics.cyclomatic import (
    CYCLOMATIC_METRIC_ID,
    analyze_cyclomatic_project,
    analyze_source_bytes_detailed,
)


def test_analyze_source_bytes_detailed_includes_base_and_decisions() -> None:
    src = "fn f() {\n  if true {}\n}\n"
    complexities, err, steps = analyze_source_bytes_detailed(
        src.encode("utf-8"),
        "rust",
        path_display="test.rs",
        debug=True,
    )
    assert err is None
    assert complexities == [2]
    kinds = [s.ast_kind for s in steps]
    assert "(base)" in kinds
    assert "if_expression" in kinds
    assert sum(s.contribution for s in steps) == 2
    assert all(s.path == "test.rs" for s in steps)
    assert all(s.metric_id == CYCLOMATIC_METRIC_ID for s in steps)


def test_format_computation_steps_rejects_metric_mismatch() -> None:
    steps = [
        ComputationStep(
            "other-metric",
            "a.rs",
            "f",
            1,
            1,
            "x",
            1,
            "r",
        )
    ]
    with pytest.raises(ValueError, match="metric_id"):
        format_computation_steps(CYCLOMATIC_METRIC_ID, steps)


def test_project_debug_collects_multiple_files(tmp_path: Path) -> None:
    tmp_path.joinpath("a.rs").write_text("fn a(){}\n", encoding="utf-8")
    tmp_path.joinpath("b.rs").write_text("fn b(){ if true {} }\n", encoding="utf-8")
    result = analyze_cyclomatic_project(tmp_path, debug=True)
    assert result.debug_steps is not None
    # a: (base); b: (base) + if_expression -> three steps
    assert len(result.debug_steps) == 3
    text = result.debug_text()
    assert "file:" in text
    assert "unit: a" in text
    assert "unit: b" in text
    # Per-file totals should be included for cyclomatic debug output.
    assert "file cyclomatic: total=1 units=1 avg=1.0000" in text
    assert "file cyclomatic: total=2 units=1 avg=2.0000" in text


def test_debug_text_empty_when_no_steps() -> None:
    from software_metrics.metrics.cyclomatic import CyclomaticProjectResult

    r = CyclomaticProjectResult(
        root=Path("/x"),
        method_count=0,
        total_complexity=0,
        average_complexity=None,
        files_scanned=0,
        debug_steps=None,
    )
    assert r.debug_text() == ""
