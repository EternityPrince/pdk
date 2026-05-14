from __future__ import annotations

import tomllib

from tests.helpers import ROOT


def test_env_example_is_trackable_and_portable():
    env_example = ROOT / ".env.example"
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert env_example.exists()
    assert "!.env.example" in gitignore
    assert "/Users/" not in env_example.read_text(encoding="utf-8")


def test_packaging_exposes_only_pdk_console_script():
    with (ROOT / "pyproject.toml").open("rb") as file:
        pyproject = tomllib.load(file)

    assert pyproject["project"]["scripts"] == {"pdk": "pdk.cli:main"}


def test_summary_extra_declares_model_download_dependency():
    with (ROOT / "pyproject.toml").open("rb") as file:
        pyproject = tomllib.load(file)

    summary_deps = pyproject["project"]["optional-dependencies"]["summary"]
    assert any(dep.startswith("huggingface-hub") for dep in summary_deps)
    assert pyproject["project"]["description"] == "Prompt Deck is a local AI context kit for the shell."


def test_install_scripts_are_present():
    assert (ROOT / "scripts" / "install.sh").exists()
    assert (ROOT / "scripts" / "download_models.py").exists()


def test_readme_documents_v02_context_workflow():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "Prompt Deck is a local AI context kit" in readme
    assert "## Session context from Markdown folders" in readme
    assert "pdk session build sport" in readme
    assert "pdk show workout --context" in readme
    assert "pdk clip workout --context" in readme
    assert "pdk session clear" in readme
    assert "saved session context" in readme
    assert "pdk context --profile default --copy" in readme
    assert "`pdk context` is the lower-level, universal context builder" in readme
    assert "`pdk export` is different again" in readme


def test_v1_docs_are_split_by_topic():
    expected = (
        "quickstart.md",
        "daily-workflows.md",
        "data-locations.md",
        "privacy-model.md",
        "backup-restore.md",
        "model-setup.md",
    )
    for name in expected:
        assert (ROOT / "docs" / name).exists()
