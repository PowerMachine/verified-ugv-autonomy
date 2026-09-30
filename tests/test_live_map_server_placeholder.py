from __future__ import annotations

import json
import threading
from pathlib import Path
from urllib.request import urlopen

from ai_autonomy_runtime.cli.run_remote_ugv_live_local import create_live_map_server
from ai_autonomy_runtime.live.ugv_live_state import LiveStateStore


def test_live_map_server_returns_placeholder_state(tmp_path: Path) -> None:
    store = LiveStateStore("server_test", tmp_path)
    server = create_live_map_server(0, store)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        with urlopen(f"http://127.0.0.1:{port}/live_state.json", timeout=2.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)

    assert payload["run_id"] == "server_test"
    assert payload["sample_count"] == 0
    assert payload["status"] == "waiting"
