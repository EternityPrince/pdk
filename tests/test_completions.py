from __future__ import annotations

from pdk.completions import bash_completion, fish_completion, zsh_completion


def test_completion_scripts_target_pdk_and_prompt_commands():
    bash = bash_completion()
    zsh = zsh_completion()
    fish = fish_completion()

    assert "complete -F _pdk_complete pdk" in bash
    assert "#compdef pdk" in zsh
    assert "complete -c pdk" in fish
    assert "session" in bash
    assert "session_commands" in zsh
    assert "init list build show clear" in fish
    assert "clear:delete last session context" in zsh
    assert "show|edit|clip|use|rm|rename|feedback|comment|versions" in bash
