from __future__ import annotations

from tests.helpers import run_pdk


def test_help_uses_pdk_program_name(tmp_path):
    helped = run_pdk(tmp_path, "--help")

    assert helped.returncode == 0
    assert "usage: pdk" in helped.stdout
    assert "Prompt Deck" in helped.stdout
    assert "AI context" in helped.stdout
    assert "Workflows:" in helped.stdout
    assert "How scope and projects fit together:" in helped.stdout
    assert "Examples" in helped.stdout
    assert "pdk session build sport" in helped.stdout
    assert "pdk show workout --context" in helped.stdout
    assert "pdk context client-a" in helped.stdout
    assert "pdk context client-a --dir src --redact --budget 12000" in helped.stdout
    assert "pdk context --profile default --copy" in helped.stdout
    assert 'pdk note add --title "Decision log" < notes.md' not in helped.stdout


def test_session_and_clip_help_show_state_flow_commands(tmp_path):
    clip_help = run_pdk(tmp_path, "clip", "--help")
    session_help = run_pdk(tmp_path, "session", "--help")
    clear_help = run_pdk(tmp_path, "session", "clear", "--help")

    assert clip_help.returncode == 0
    assert "--context" in clip_help.stdout
    assert session_help.returncode == 0
    assert "clear" in session_help.stdout
    assert "pdk clip workout --context" in session_help.stdout
    assert clear_help.returncode == 0
    assert "Delete .pdk/session.md" in clear_help.stdout
