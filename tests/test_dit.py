"""Tests for DIT (depth of inheritance tree)."""

from __future__ import annotations

from pathlib import Path

import pytest

from software_metrics.metrics.dit import analyze_dit_project


def test_ts_two_level_chain(tmp_path: Path) -> None:
    tmp_path.joinpath("p.ts").write_text("export class Parent {}\n", encoding="utf-8")
    tmp_path.joinpath("c.ts").write_text(
        'import { Parent } from "./p";\nexport class Child extends Parent {}\n',
        encoding="utf-8",
    )
    r = analyze_dit_project(tmp_path)
    assert r.classes_count == 2
    assert r.maximum_dit == 2
    assert r.average_dit == pytest.approx(1.5)


def test_ts_external_super_depth_two(tmp_path: Path) -> None:
    tmp_path.joinpath("x.ts").write_text(
        "export class X extends HTMLElement {}\n",
        encoding="utf-8",
    )
    r = analyze_dit_project(tmp_path)
    assert r.classes_count == 1
    assert r.maximum_dit == 2
    assert r.average_dit == pytest.approx(2.0)


def test_kotlin_super_chain(tmp_path: Path) -> None:
    tmp_path.joinpath("P.kt").write_text(
        "open class Parent\n",
        encoding="utf-8",
    )
    tmp_path.joinpath("C.kt").write_text(
        "class Child : Parent()\n",
        encoding="utf-8",
    )
    r = analyze_dit_project(tmp_path)
    assert r.classes_count == 2
    assert r.maximum_dit == 2


def test_empty_project(tmp_path: Path) -> None:
    r = analyze_dit_project(tmp_path)
    assert r.classes_count == 0
    assert r.average_dit is None
