from __future__ import annotations

import argparse
import json

from ai_autonomy_runtime.adapters.jackal.command_bridge_client import CommandBridgeClient
from ai_autonomy_runtime.adapters.jackal.executor_safety import ExecutorSafetyConfig
from ai_autonomy_runtime.adapters.jackal.ssh_command_bridge import BridgeConfig
from ai_autonomy_runtime.core.audit_logger import _to_jsonable


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a manual low-risk VerifiedCommand through the SSH bridge.")
    parser.add_argument("--bridge-config", default="configs/bridge.yaml")
    parser.add_argument("--safety-config", default="configs/jackal_executor_safety.yaml")
    parser.add_argument("--host", default=None)
    parser.add_argument("--user", default=None)
    parser.add_argument("--command", choices=["forward", "back", "left", "right", "stop"], default="stop")
    parser.add_argument("--duration-ms", type=int, default=700)
    parser.add_argument("--linear", type=float, default=0.05)
    parser.add_argument("--angular", type=float, default=0.10)
    parser.add_argument("--sequence-id", type=int, default=None)
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--armed", action="store_true", help="Operator approval and bridge permission for SSH execution.")
    parser.add_argument("--dry-run", action="store_true", help="Audit the command locally without calling SSH.")
    args = parser.parse_args()

    bridge_config = BridgeConfig.from_yaml(args.bridge_config)
    if args.host is not None:
        bridge_config.host = args.host
    if args.user is not None:
        bridge_config.user = args.user

    safety_config = ExecutorSafetyConfig.from_yaml(args.safety_config)
    client = CommandBridgeClient(bridge_config, safety_config, runs_dir=args.runs_dir)
    command = client.build_manual_command(
        command=args.command,
        duration_ms=args.duration_ms,
        linear=args.linear,
        angular=args.angular,
        armed=args.armed,
        sequence_id=args.sequence_id,
    )
    dry_run = args.dry_run or (bridge_config.default_dry_run and not args.armed)
    receipt = client.run(command, armed=args.armed, dry_run=dry_run)
    print(json.dumps(_to_jsonable(receipt), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
