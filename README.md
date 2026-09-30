# Verified Autonomy Runtime for a UGV

A research and bench-test toolkit for separating AI-generated action candidates from commands that may reach a physical robot. It combines deterministic verification, dry-run command previews, operator approval, and a small 2D simulation.

> Research code, not a certified robot safety system. The public snapshot uses documentation-only network addresses. It does not include lab access details, model weights, field logs, or live telemetry. No live device connection is needed to run the tests or simulation.

## Safety path

```text
Action candidate → schema / evidence / permission / safety checks
                 → preview → operator approval → verified command
                 → executor checks → dry-run receipt
```

The default workflows are read-only or dry-run. An isolated, readiness-gated physical bench executor exists in the code for controlled testing; it must not be used on a live robot without a separate safety review and appropriate supervision. LLM output is never intended to publish directly to `/cmd_vel`.

## Run locally

Requires Python 3.10 or newer.

```bash
python -m venv .venv
# Activate the virtual environment for your shell.
python -m pip install -e .[dev]
python -m pytest -q
python -m ai_autonomy_runtime.cli.run_ugv_sim --help
python -m ai_autonomy_runtime.cli.run_mock_mission --help
```

The tests cover schema checks, command expiry/replay rejection, velocity limits, dry-run execution, observation, simulation, and scenario supervision. The local test suite passed 74 tests when this snapshot was prepared. Hardware-specific behavior was not revalidated for this public export.

## Repository structure

```text
ai_autonomy_runtime/   runtime, verifiers, adapters, simulation, CLI
configs/              example safety and runtime configuration
tests/                automated checks
PROJECT.md            research question and initial milestone
```

The example address `192.0.2.10` is a reserved documentation address. Supply your own authorized configuration only in an isolated test environment; do not treat the included defaults as deployment settings.

This project demonstrates an engineering approach to bounded autonomy, not autonomous navigation performance or production readiness.

## Historical bench evidence

The [June 2026 UGV bench notes](docs/june-2026-ugv-bench-notes.md) document a separate, supervised hardware check: ROS topic discovery, remote manual wheel commands with the robot inverted, and a 2D observation view. The public code remains a sanitized research snapshot and does not reproduce that hardware run.
