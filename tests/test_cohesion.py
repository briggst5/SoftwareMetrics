"""Tests for LCOM cohesion metric."""

from __future__ import annotations

from pathlib import Path

import pytest

from software_metrics.metrics.cohesion import analyze_cohesion_project


def test_ts_disjoint_fields_high_lcom(tmp_path: Path) -> None:
    tmp_path.joinpath("c.ts").write_text(
        "class C {\n"
        "  a = 1;\n"
        "  b = 2;\n"
        "  u() { return this.a; }\n"
        "  v() { return this.b; }\n"
        "}\n",
        encoding="utf-8",
    )
    r = analyze_cohesion_project(tmp_path)
    assert r.units_analyzed == 1
    assert r.total_lcom == 1
    assert r.average_lcom == pytest.approx(1.0)


def test_ts_shared_field_zero_lcom(tmp_path: Path) -> None:
    tmp_path.joinpath("c.ts").write_text(
        "class C {\n"
        "  a = 1;\n"
        "  u() { return this.a; }\n"
        "  v() { return this.a; }\n"
        "}\n",
        encoding="utf-8",
    )
    r = analyze_cohesion_project(tmp_path)
    assert r.total_lcom == 0


def test_rust_impl_lcom(tmp_path: Path) -> None:
    tmp_path.joinpath("lib.rs").write_text(
        "pub struct S { pub a: i32, pub b: i32 }\n"
        "impl S {\n"
        "    fn u(&self) -> i32 { self.a }\n"
        "    fn v(&self) -> i32 { self.b }\n"
        "}\n",
        encoding="utf-8",
    )
    r = analyze_cohesion_project(tmp_path)
    assert r.units_analyzed == 1
    assert r.total_lcom == 1


def test_kotlin_class_lcom(tmp_path: Path) -> None:
    tmp_path.joinpath("K.kt").write_text(
        "class K(val x: Int) {\n"
        "  val y = 2\n"
        "  fun a() = x\n"
        "  fun b() = y\n"
        "}\n",
        encoding="utf-8",
    )
    r = analyze_cohesion_project(tmp_path)
    assert r.units_analyzed == 1
    assert r.total_lcom == 1


def test_empty_project(tmp_path: Path) -> None:
    r = analyze_cohesion_project(tmp_path)
    assert r.units_analyzed == 0
    assert r.average_lcom is None
