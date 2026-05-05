"""Command-line entrypoint."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from software_metrics.metrics.cohesion import analyze_cohesion_project
from software_metrics.metrics.dit import analyze_dit_project
from software_metrics.metrics.coupling import analyze_coupling_project
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
        choices=["cyclomatic-complexity", "coupling", "cohesion", "dit"],
        required=True,
        help="Which metric to compute.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help=(
            "Print how each score is computed (decision points and contributions). "
            "Supported for all implemented metrics."
        ),
    )
    args = parser.parse_args()
    root: Path = args.root.resolve()
    if not root.is_dir():
        print(f"error: --root is not a directory: {root}", file=sys.stderr)
        sys.exit(2)

    if args.metric == "cyclomatic-complexity":
        result = analyze_cyclomatic_project(root, debug=args.debug)
        print(result.summary_text())
        if args.debug:
            dbg = result.debug_text()
            if dbg:
                print()
                print(dbg)
            else:
                print(
                    "\n[debug] No computation trace "
                    "(no functions found or empty project)."
                )
        if result.files_with_errors:
            for path, msg in result.files_with_errors:
                print(f"warning: {path}: {msg}", file=sys.stderr)

    elif args.metric == "coupling":
        result = analyze_coupling_project(root, debug=args.debug)
        print(result.summary_text())
        if args.debug:
            dbg = result.debug_text()
            if dbg:
                print()
                print(dbg)
            else:
                print(
                    "\n[debug] No computation trace "
                    "(no resolved internal edges or empty project)."
                )
        if result.files_with_parse_or_io_errors:
            for path, msg in result.files_with_parse_or_io_errors:
                print(f"warning: {path}: {msg}", file=sys.stderr)

    elif args.metric == "cohesion":
        result = analyze_cohesion_project(root, debug=args.debug)
        print(result.summary_text())
        if args.debug:
            dbg = result.debug_text()
            if dbg:
                print()
                print(dbg)
            else:
                print(
                    "\n[debug] No computation trace "
                    "(no qualifying classes or impls)."
                )
        if result.files_with_errors:
            for path, msg in result.files_with_errors:
                print(f"warning: {path}: {msg}", file=sys.stderr)

    elif args.metric == "dit":
        result = analyze_dit_project(root, debug=args.debug)
        print(result.summary_text())
        if args.debug:
            dbg = result.debug_text()
            if dbg:
                print()
                print(dbg)
            else:
                print("\n[debug] No computation trace (no classes found).")
        if result.files_with_errors:
            for path, msg in result.files_with_errors:
                print(f"warning: {path}: {msg}", file=sys.stderr)


if __name__ == "__main__":
    main()
