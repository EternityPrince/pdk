from __future__ import annotations

from pdk.system_adapters import CommandSpec, SystemAdapter
from tests.helpers import fake_path_env, run_pdk


def test_system_adapter_finds_first_available_clipboard_command(tmp_path, monkeypatch):
    env = fake_path_env(tmp_path, {"wl-copy": "#!/bin/sh\ncat >/dev/null\n"})
    monkeypatch.setenv("PATH", env["PATH"])
    adapter = SystemAdapter(
        name="test",
        clipboard_copy_candidates=(CommandSpec(("missing-copy",)), CommandSpec(("wl-copy",))),
        clipboard_paste_candidates=(),
    )

    command = adapter.clipboard_copy_command()

    assert command is not None
    assert command.args == ("wl-copy",)


def test_doctor_system_reports_runtime_paths_and_adapters(tmp_path):
    env = fake_path_env(
        tmp_path,
        {
            "pbcopy": "#!/bin/sh\ncat >/dev/null\n",
            "pbpaste": "#!/bin/sh\nprintf clipboard\n",
            "fzf": "#!/bin/sh\nexit 0\n",
        },
    )

    result = run_pdk(tmp_path, "doctor", "--system", env=env)

    assert result.returncode == 0
    assert "System\n" in result.stdout
    assert "selected_database\t" in result.stdout
    assert "global_database\t" in result.stdout
    assert "file_index\t" in result.stdout
    assert "privacy_configs\t" in result.stdout
    assert "clipboard_copy\tpbcopy" in result.stdout
    assert "clipboard_paste\tpbpaste" in result.stdout
    assert "fzf\tfzf" in result.stdout
    assert "extra_summary\t" in result.stdout
