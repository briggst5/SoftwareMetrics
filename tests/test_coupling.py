"""Tests for file-level coupling (fan-in / fan-out)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from software_metrics.metrics.coupling import analyze_coupling_project


def test_ts_relative_import_creates_one_edge(tmp_path: Path) -> None:
    """a.ts imports ./b → fan-out(a)=1, fan-in(b)=1."""
    tmp_path.joinpath("b.ts").write_text("export const x = 1;\n", encoding="utf-8")
    tmp_path.joinpath("a.ts").write_text(
        'import { x } from "./b";\nconsole.log(x);\n',
        encoding="utf-8",
    )
    r = analyze_coupling_project(tmp_path)
    assert r.files_count == 2
    assert r.internal_edge_count == 1
    assert r.average_fan_out == pytest.approx(0.5)
    assert r.average_fan_in == pytest.approx(0.5)
    assert r.ratio_of_average_fan_in_to_fan_out == pytest.approx(1.0)
    # Only a.ts has fan-out > 0; its ratio fan_in/fan_out = 0/1 = 0.
    assert r.average_file_fan_in_fan_out_ratio == pytest.approx(0.0)


def test_coupling_empty_project(tmp_path: Path) -> None:
    r = analyze_coupling_project(tmp_path)
    assert r.files_count == 0
    assert r.internal_edge_count == 0
    assert r.average_fan_in == 0.0
    assert r.average_fan_out == 0.0
    assert r.ratio_of_average_fan_in_to_fan_out is None


def test_coupling_debug_includes_edge(tmp_path: Path) -> None:
    tmp_path.joinpath("b.ts").write_text("export const x = 1;\n", encoding="utf-8")
    tmp_path.joinpath("a.ts").write_text('import { x } from "./b";\n', encoding="utf-8")
    r = analyze_coupling_project(tmp_path, debug=True)
    assert r.debug_steps
    text = r.debug_text()
    assert "resolved_import" in text
    assert "→" in text


def test_ts_tsconfig_paths_alias_resolves_edge(tmp_path: Path) -> None:
    """Imports like @/… map via compilerOptions.paths to scanned files."""
    tsconfig = {
        "compilerOptions": {
            "baseUrl": ".",
            "paths": {"@/*": ["./src/*"]},
        },
    }
    tmp_path.joinpath("tsconfig.json").write_text(
        json.dumps(tsconfig),
        encoding="utf-8",
    )
    src = tmp_path / "src"
    src.mkdir()
    src.joinpath("util.ts").write_text("export const u = 1;\n", encoding="utf-8")
    src.joinpath("app.ts").write_text('import { u } from "@/util";\n', encoding="utf-8")
    r = analyze_coupling_project(tmp_path)
    assert r.files_count == 2
    assert r.internal_edge_count == 1


def test_coupling_summary_note_when_no_resolvable_edges(tmp_path: Path) -> None:
    tmp_path.joinpath("a.ts").write_text('import React from "react";\n', encoding="utf-8")
    tmp_path.joinpath("b.ts").write_text("export const x = 1;\n", encoding="utf-8")
    r = analyze_coupling_project(tmp_path)
    assert r.internal_edge_count == 0
    assert "Note:" in r.summary_text()
