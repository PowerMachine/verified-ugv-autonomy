from __future__ import annotations

from pathlib import Path


class CompileTestRunner:
    def run_python_compile(self, root: str | Path) -> dict[str, object]:
        root_path = Path(root)
        files = list(root_path.rglob("*.py"))
        return {"status": "not_run", "reason": "use python -m compileall for full compile checks", "python_files": len(files)}
