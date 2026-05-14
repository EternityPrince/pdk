from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FAKE_EDITOR = r"""
from pathlib import Path
import os
import sys

path = Path(sys.argv[-1])
values = os.environ["PDK_FAKE_EDITOR_VALUES"].split("\x1e")
state = Path(os.environ["PDK_FAKE_EDITOR_STATE"])
index = int(state.read_text(encoding="utf-8")) if state.exists() else 0
path.write_text(values[index], encoding="utf-8")
state.write_text(str(index + 1), encoding="utf-8")
"""


def run_pdk(
    tmp_path: Path,
    *args: str,
    input: str | None = None,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
):
    full_env = os.environ.copy()
    full_env["PDK_HOME"] = str(tmp_path / "pdk-home")
    full_env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + full_env.get("PYTHONPATH", "")
    if env:
        full_env.update(env)

    return subprocess.run(
        [sys.executable, "-m", "pdk.cli", *args],
        input=input,
        text=True,
        capture_output=True,
        env=full_env,
        cwd=cwd,
        check=False,
    )


def editor_env(tmp_path: Path, values: list[str]) -> dict[str, str]:
    editor = tmp_path / "fake_editor.py"
    editor.write_text(FAKE_EDITOR, encoding="utf-8")
    state = tmp_path / "fake_editor_state.txt"
    return {
        "EDITOR": f"{sys.executable} {editor}",
        "PDK_FAKE_EDITOR_VALUES": "\x1e".join(values),
        "PDK_FAKE_EDITOR_STATE": str(state),
    }


def fake_path_env(tmp_path: Path, commands: dict[str, str], extra: dict[str, str] | None = None) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, body in commands.items():
        path = bin_dir / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)
    env = {"PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", "")}
    if extra:
        env.update(extra)
    return env
