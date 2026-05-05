"""Command-line entrypoint."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from software_metrics.metrics.cyclomatic import analyze_cyclomatic_project


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Measure software metrics for Kotlin, TypeScript/React, and Rust sources "
            "under a project root."
        ),
    )
    parser.add_argument(
        "--root",
        type=Path,
        required=True,
        help="Root directory of the project to analyze.",
    )
    parser.add_argument(
        "--metric",
        choices=["cyclomatic-complexity"],
        required=True,
        help="Which metric to compute.",
    )
    args = parser.parse_args()
    root: Path = args.root.resolve()
    if not root.is_dir():
        print(f"error: --root is not a directory: {root}", file=sys.stderr)
        sys.exit(2)

    if args.metric == "cyclomatic-complexity":
        result = analyze_cyclomatic_project(root)
        print(result.summary_text())
        if result.files_with_errors:
            for path, msg in result.files_with_errors:
                print(f"warning: {path}: {msg}", file=sys.stderr)


if __name__ == "__main__":
    main()
