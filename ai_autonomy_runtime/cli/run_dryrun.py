from __future__ import annotations

import argparse

from ai_autonomy_runtime.cli.common import print_json
from ai_autonomy_runtime.cli.run_mock_mission import run_mock_mission


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate and dry-run a safe action candidate.")
    parser.add_argument("--goal", required=True)
    parser.add_argument("--output", default="runs/jackal_dryrun")
    args = parser.parse_args()
    print_json(run_mock_mission(args.goal, "full_governed", args.output))


if __name__ == "__main__":
    main()
