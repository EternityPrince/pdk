from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pdk.model_loader import load_env_file, local_model_dir  # noqa: E402
from pdk.summary import DEFAULT_SUMMARY_MODEL  # noqa: E402


def main() -> int:
    load_env_file(ROOT)
    target = local_model_dir(DEFAULT_SUMMARY_MODEL)
    if target is None:
        print("Set PDK_LLM_MODEL_DIR in .env before downloading models.", file=sys.stderr)
        return 1

    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        from huggingface_hub import snapshot_download
    except ModuleNotFoundError:
        print("Missing huggingface_hub. Run `uv sync --all-extras --dev` first.", file=sys.stderr)
        return 1

    snapshot_download(
        repo_id=DEFAULT_SUMMARY_MODEL,
        local_dir=str(target),
    )
    print(f"Downloaded {DEFAULT_SUMMARY_MODEL} to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
