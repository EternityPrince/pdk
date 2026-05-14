from __future__ import annotations

from pdk.model_loader import LLM_MODEL_DIR_ENV, SUMMARY_MODEL_PATH_ENV, load_env_file, resolve_summary_model
from pdk.summary import DEFAULT_SUMMARY_MODEL


def test_load_env_file_reads_nearest_private_env(tmp_path, monkeypatch):
    model_dir = tmp_path / "models"
    (tmp_path / ".env").write_text(f"{LLM_MODEL_DIR_ENV}={model_dir}\n", encoding="utf-8")
    nested = tmp_path / "project" / "nested"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    monkeypatch.delenv(LLM_MODEL_DIR_ENV, raising=False)

    loaded = load_env_file()

    assert loaded == tmp_path / ".env"
    assert resolve_summary_model(DEFAULT_SUMMARY_MODEL) == DEFAULT_SUMMARY_MODEL


def test_resolve_summary_model_uses_downloaded_local_dir(tmp_path, monkeypatch):
    model_root = tmp_path / "models"
    model_path = model_root / "gemma-3-text-4b-it-4bit"
    model_path.mkdir(parents=True)
    (tmp_path / ".env").write_text(f"{LLM_MODEL_DIR_ENV}={model_root}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(LLM_MODEL_DIR_ENV, raising=False)

    assert resolve_summary_model(DEFAULT_SUMMARY_MODEL) == str(model_path)


def test_resolve_summary_model_prefers_explicit_model_path(tmp_path, monkeypatch):
    model_root = tmp_path / "models"
    downloaded = model_root / "gemma-3-text-4b-it-4bit"
    explicit = tmp_path / "explicit-model"
    downloaded.mkdir(parents=True)
    explicit.mkdir()
    monkeypatch.setenv(LLM_MODEL_DIR_ENV, str(model_root))
    monkeypatch.setenv(SUMMARY_MODEL_PATH_ENV, str(explicit))

    assert resolve_summary_model(DEFAULT_SUMMARY_MODEL) == str(explicit)
