"""
Structured debug output for metrics.

Any metric can emit :class:`ComputationStep` rows. Use
:func:`format_computation_steps` for a stable CLI trace; other serializers can be
added without changing metric code.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class ComputationStep:
    """One additive contribution toward a metric score for a single code unit."""

    metric_id: str
    path: str
    unit: str
    line: int
    column: int
    ast_kind: str
    contribution: int
    reason: str


def format_computation_steps(
    metric_id: str,
    steps: list[ComputationStep],
    *,
    header: str | None = None,
) -> str:
    """Render grouped trace: file → unit → line items → unit total."""
    if not steps:
        return ""

    lines: list[str] = []
    if header:
        lines.append(header)

    lines.append(f"[debug] metric={metric_id}")

    grouped: dict[str, dict[str, list[ComputationStep]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for s in steps:
        if s.metric_id != metric_id:
            raise ValueError(
                f"step metric_id {s.metric_id!r} does not match {metric_id!r}"
            )
        grouped[s.path][s.unit].append(s)

    for path in sorted(grouped.keys()):
        lines.append(f"  file: {path}")
        units_map = grouped[path]
        # Sort units by first contribution location in source
        units_ordered = sorted(
            units_map.keys(),
            key=lambda u: (
                min(st.line for st in units_map[u]),
                min(st.column for st in units_map[u]),
            ),
        )
        for unit in units_ordered:
            usteps = units_map[unit]
            lines.append(f"    unit: {unit}")
            unit_total = 0
            for st in usteps:
                unit_total += st.contribution
                loc = f"line {st.line}, col {st.column}"
                suffix = f" — {st.reason}" if st.reason else ""
                lines.append(
                    f"      +{st.contribution} @ {loc} [{st.ast_kind}]{suffix}"
                )
            lines.append(f"      = {unit_total} (sum of contributions for this unit)")

    if metric_id == "cyclomatic-complexity":
        lines.append(
            "  note: For cyclomatic complexity, contributions include "
            "a +1 (base) entry plus decision weights; the sum equals the "
            "reported complexity for that unit."
        )
    elif metric_id == "coupling":
        lines.append(
            "  note: Each +1 is one resolved internal dependency edge "
            "(distinct target file). Sums per unit are edge counts from that file."
        )
    elif metric_id == "cohesion":
        lines.append(
            "  note: Each row is one class / Rust impl unit; contribution is its "
            "LCOM score (higher ⇒ lower cohesion)."
        )
    elif metric_id == "dit":
        lines.append(
            "  note: Contribution is DIT depth per class (extends / superclass only)."
        )

    return "\n".join(lines)
