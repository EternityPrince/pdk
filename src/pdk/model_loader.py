from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


DOTENV_FILE = ".env"
LLM_MODEL_DIR_ENV = "PDK_LLM_MODEL_DIR"
SUMMARY_MODEL_PATH_ENV = "PDK_SUMMARY_MODEL_PATH"


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _dotenv_paths(start: Path | None = None) -> list[Path]:
    cwd = (start or Path.cwd()).resolve()
    return [directory / DOTENV_FILE for directory in (cwd, *cwd.parents)]


def load_env_file(start: Path | None = None) -> Path | None:
    for path in _dotenv_paths(start):
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key:
                continue
            os.environ.setdefault(key, _unquote(value.strip()))
        return path
    return None


def model_cache_dir(env_var: str = LLM_MODEL_DIR_ENV) -> Path | None:
    load_env_file()
    value = os.environ.get(env_var)
    return Path(value).expanduser() if value else None


def model_dir_name(model_id: str) -> str:
    return model_id.rstrip("/").rsplit("/", 1)[-1]


def local_model_dir(model_id: str, *, env_var: str = LLM_MODEL_DIR_ENV) -> Path | None:
    cache_dir = model_cache_dir(env_var)
    if cache_dir is None:
        return None
    return cache_dir / model_dir_name(model_id)


def resolve_summary_model(model_id: str) -> str:
    load_env_file()
    explicit = os.environ.get(SUMMARY_MODEL_PATH_ENV)
    if explicit:
        return str(Path(explicit).expanduser())
    local_dir = local_model_dir(model_id)
    if local_dir is not None and local_dir.exists():
        return str(local_dir)
    return model_id


@lru_cache(maxsize=2)
def load_mlx_model(model_name_or_path: str):
    try:
        from mlx_lm import load
    except ModuleNotFoundError as exc:
        raise RuntimeError("Gemma digest generation requires installing the `summary` extra") from exc
    return load(model_name_or_path)
