# SoftwareMetrics — agent instructions

## Purpose

Build a **multi-language software metrics** tool. Initial targets: **Kotlin**, **TypeScript + React**, and **Rust**.

## Metrics to support

| Area | Metrics / checks |
|------|------------------|
| Complexity | Cyclomatic complexity |
| Structure | Coupling, cohesion (average LCOM) |
| Duplication | Code duplication |
| OOP style | Ratio of composition over inheritance |
| Conventions | Adherence to standard naming (per language / ecosystem) |
| Design | Single responsibility principle (heuristics + human-in-the-loop where needed) |
| Documentation | LLM-assisted assessment of comments and in-code documentation (optional / gated) |
| Size | Method and class (type) length |

## Architecture principles

1. **Language backends** — isolate parsing and language-specific rules per stack (Kotlin, TS/React, Rust). Share a common **metric model** and reporting layer.
2. **Deterministic first** — prefer static analysis and AST-based metrics for reproducibility. Use **LLM only** where explicitly requested (e.g. doc quality), with clear inputs/outputs and cost controls.
3. **Extensibility** — new metrics should plug into the same pipeline without rewriting unrelated language code.
4. **Transparency** — each reported value should be traceable (file, symbol, rule id, and optional evidence).

## Repository layout (evolve as code lands)

- Prefer `crates/` or `packages/` per language analyzer plus a shared core once the stack is chosen.
- Keep configuration (thresholds, includes/excludes) separate from analyzer logic.

## CLI (Python prototype)

From the repo root, with a virtual environment:

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e .
software-metrics --root /path/to/project --metric cyclomatic-complexity
software-metrics --root /path/to/project --metric cyclomatic-complexity --debug
software-metrics --root /path/to/project --metric coupling --debug
software-metrics --root /path/to/project --metric cohesion --debug
```

Use `--debug` to print how each score is built (cyclomatic: AST decisions; coupling: resolved internal import edges). Future metrics should emit the same `ComputationStep` rows via `software_metrics.debug_report`.

`--metric cyclomatic-complexity` reports the **average McCabe-style cyclomatic complexity per function/method** (Kotlin `.kt`/`.kts`, TypeScript `.ts`/`.tsx`, Rust `.rs`). Ordinary call sites are not treated as decisions.

`--metric coupling` treats each source file as a module and estimates **fan-in** / **fan-out** from **resolved project-internal imports** only (relative TS/TSX imports, Kotlin imports matched to file paths, Rust `crate::` / `super::` / `mod foo;` heuristics under `src/`). It reports average fan-in, average fan-out, their ratio, and the mean of per-file `fan_in/fan_out` over files with fan-out greater than zero.

`--metric cohesion` reports **average LCOM** (Lack of Cohesion of Methods, CK-style) over Kotlin classes, TS/TSX classes, and Rust `impl Type` blocks paired with `struct Type` in the **same file**. Field use is inferred statically (identifiers plus `this.` / `self.` field access). Units need at least two instance methods.

Run unit tests after installing dev dependencies:

```bash
pip install -e ".[dev]"
pytest
```

There is broad coverage for cyclomatic scoring (Rust / Kotlin / TS / TSX snippets, nested units vs closures/lambdas, filesystem skips, parse failures, and project aggregation). See `tests/test_cyclomatic.py` and `tests/test_cyclomatic_corners.py`.

## When implementing

- Match existing patterns in the repo; avoid drive-by refactors.
- Add or update tests when behavior is non-trivial.
- Document new metrics in user-facing help or docs the project adopts.

## Instruction priority

Project-specific rules in `.cursor/rules/` and this file override generic assumptions. User messages override everything.
