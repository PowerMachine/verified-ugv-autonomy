from __future__ import annotations

import argparse
import json
import os
import shlex
import signal
import subprocess
import threading
import time
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ai_autonomy_runtime.live.ugv_live_state import LiveStateStore, live_map_html, parse_telemetry_line


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a Windows-local UGV live observation server fed by SSH JSONL.")
    parser.add_argument("--host", default="192.0.2.10")
    parser.add_argument("--user", default="robot")
    parser.add_argument("--remote-project-dir", default="/home/robot/ai-autonomy-ugv")
    parser.add_argument("--identity-file", default=_default_identity_file())
    parser.add_argument("--run-id", default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    parser.add_argument("--duration", type=float, default=30.0)
    parser.add_argument("--sample-hz", type=float, default=5.0)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--output", default="local_outputs/ugv_live")
    parser.add_argument("--open-browser", action="store_true")
    parser.add_argument("--dry-run-server-only", action="store_true")
    parser.add_argument("--skip-code-sync", action="store_true")
    args = parser.parse_args()

    run_dir = Path(args.output) / args.run_id
    store = LiveStateStore(args.run_id, run_dir)
    server = _create_server(args.port, store)
    server_thread = threading.Thread(target=server.serve_forever, name="ugv-live-http", daemon=True)
    server_thread.start()
    url = f"http://127.0.0.1:{args.port}/live_map.html?run={args.run_id}"
    print(f"Local live map: {url}", flush=True)
    print(f"Local output: {run_dir}", flush=True)
    if args.open_browser:
        webbrowser.open(url)

    stop_event = threading.Event()
    process: subprocess.Popen[str] | None = None

    def request_stop(_signum: int, _frame: Any) -> None:
        stop_event.set()
        if process is not None and process.poll() is None:
            process.terminate()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    started = time.monotonic()
    try:
        if args.dry_run_server_only:
            store.add_event({"event_type": "dry_run_server_only", "severity": "info", "message": "SSH disabled"})
        else:
            if not args.skip_code_sync:
                _sync_streamer_code(args)
            process = _start_ssh_stream(args)
            _start_reader_threads(process, store)
        _wait_for_duration_or_process(args.duration, started, process, stop_event)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3.0)
        store.mark_complete("interrupted" if stop_event.is_set() else "duration_elapsed")
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=3.0)

    artifacts = store.write_final_artifacts()
    print(json.dumps({"run_id": args.run_id, "url": url, "artifacts": artifacts}, indent=2), flush=True)


def create_live_map_server(port: int, store: LiveStateStore) -> ThreadingHTTPServer:
    return _create_server(port, store)


def _create_server(port: int, store: LiveStateStore) -> ThreadingHTTPServer:
    handler_class = _handler_for_store(store)
    try:
        return ThreadingHTTPServer(("127.0.0.1", port), handler_class)
    except OSError as exc:
        raise SystemExit(
            f"Could not bind local live map server to 127.0.0.1:{port}: {exc}. "
            f"Use --port with a free port, for example --port {port + 1}."
        ) from exc


def _handler_for_store(store: LiveStateStore) -> type[BaseHTTPRequestHandler]:
    class LiveMapHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            if path in {"/", "/live_map.html"}:
                self._send_text(live_map_html(), "text/html; charset=utf-8")
                return
            if path == "/live_state.json":
                self._send_json(store.snapshot())
                return
            if path == "/trajectory.csv":
                csv_path = store.export_trajectory_csv()
                if csv_path and csv_path.exists():
                    self._send_bytes(csv_path.read_bytes(), "text/csv; charset=utf-8")
                else:
                    self._send_text("t_s,x_m,y_m,yaw_rad,yaw_deg,linear_x,angular_z,source\n", "text/csv; charset=utf-8")
                return
            if path == "/healthz":
                snap = store.snapshot()
                self._send_json(
                    {
                        "ok": True,
                        "run_id": store.run_id,
                        "sample_count": snap["sample_count"],
                        "status": snap["status"],
                    }
                )
                return
            self.send_error(404)

        def log_message(self, _format: str, *_args: Any) -> None:
            return

        def _send_json(self, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send_bytes(body, "application/json; charset=utf-8")

        def _send_text(self, text: str, content_type: str) -> None:
            self._send_bytes(text.encode("utf-8"), content_type)

        def _send_bytes(self, body: bytes, content_type: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return LiveMapHandler


def _start_ssh_stream(args: argparse.Namespace) -> subprocess.Popen[str]:
    command = build_ssh_stream_command(args)
    return subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )


def build_ssh_stream_command(args: argparse.Namespace) -> list[str]:
    target = f"{args.user}@{args.host}"
    ssh_args = _ssh_args(args.identity_file)
    remote_command = (
        f"cd '{args.remote_project_dir}' && "
        "(deactivate 2>/dev/null || true) && "
        "source /opt/ros/noetic/setup.bash && "
        f"export ROS_MASTER_URI=http://{args.host}:11311 && "
        f"export ROS_IP={args.host} && "
        'export PYTHONPATH="$PWD:${PYTHONPATH:-}" && '
        "python3 -m ai_autonomy_runtime.cli.stream_ugv_state "
        f"--run-id '{args.run_id}' "
        f"--sample-hz {args.sample_hz} "
        f"--duration {args.duration}"
    )
    return ["ssh", *ssh_args, target, f"bash -lc {shlex.quote(remote_command)}"]


def _start_reader_threads(process: subprocess.Popen[str], store: LiveStateStore) -> None:
    stdout_thread = threading.Thread(target=_read_stdout, args=(process, store), name="ugv-live-ssh-stdout", daemon=True)
    stderr_thread = threading.Thread(target=_read_stderr, args=(process, store), name="ugv-live-ssh-stderr", daemon=True)
    stdout_thread.start()
    stderr_thread.start()


def _read_stdout(process: subprocess.Popen[str], store: LiveStateStore) -> None:
    assert process.stdout is not None
    for line in process.stdout:
        parsed = parse_telemetry_line(line)
        if parsed.kind == "state" and parsed.payload is not None:
            store.apply_state(parsed.payload)
        elif parsed.kind == "event" and parsed.payload is not None:
            store.add_event(parsed.payload)
        elif parsed.kind == "malformed":
            store.add_malformed_line(parsed.raw_line, parsed.error)
    return_code = process.poll()
    store.mark_stream_disconnected(f"stdout ended; return_code={return_code}")


def _read_stderr(process: subprocess.Popen[str], store: LiveStateStore) -> None:
    assert process.stderr is not None
    for line in process.stderr:
        message = line.strip()
        if message:
            store.add_event({"event_type": "ssh_stderr", "severity": "info", "message": message})


def _wait_for_duration_or_process(
    duration_s: float,
    started: float,
    process: subprocess.Popen[str] | None,
    stop_event: threading.Event,
) -> None:
    while not stop_event.is_set():
        elapsed = time.monotonic() - started
        if duration_s > 0 and elapsed >= duration_s:
            return
        if process is not None and process.poll() is not None and duration_s <= 0:
            return
        time.sleep(0.1)


def _sync_streamer_code(args: argparse.Namespace) -> None:
    target = f"{args.user}@{args.host}"
    ssh_args = _ssh_args(args.identity_file)
    cli_dir = Path(__file__).parent
    sources = [
        cli_dir / "stream_ugv_state.py",
        cli_dir / "run_ugv_teleop.py",
    ]
    mkdir_command = f"mkdir -p '{args.remote_project_dir}/ai_autonomy_runtime/cli'"
    subprocess.run(["ssh", *ssh_args, target, mkdir_command], check=True)
    for source in sources:
        subprocess.run(
            ["scp", *_scp_args(args.identity_file), str(source), f"{target}:{args.remote_project_dir}/ai_autonomy_runtime/cli/"],
            check=True,
        )


def _ssh_args(identity_file: str | None) -> list[str]:
    args = ["-o", "ConnectTimeout=30", "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=3"]
    if identity_file and Path(identity_file).exists():
        return ["-i", identity_file, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", *args]
    return args


def _scp_args(identity_file: str | None) -> list[str]:
    return _ssh_args(identity_file)


def _default_identity_file() -> str | None:
    home = os.environ.get("USERPROFILE") or os.environ.get("HOME")
    if not home:
        return None
    return str(Path(home) / ".ssh" / "id_ed25519_ugv")


if __name__ == "__main__":
    main()
