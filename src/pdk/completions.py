from __future__ import annotations

COMPLETION_COMMANDS = (
    "add",
    "browse",
    "check",
    "clip",
    "comment",
    "completions",
    "context",
    "doctor",
    "duplicates",
    "edit",
    "export",
    "feedback",
    "file",
    "files",
    "find",
    "import",
    "index",
    "list",
    "move",
    "note",
    "project",
    "privacy",
    "redact",
    "rename",
    "rm",
    "security",
    "show",
    "scan",
    "digest",
    "stale",
    "stats",
    "tag",
    "tags",
    "usage",
    "use",
    "versions",
)


def bash_completion() -> str:
    commands = " ".join(COMPLETION_COMMANDS)
    return f"""_pdk_complete()
{{
    local cur prev
    COMPREPLY=()
    cur="${{COMP_WORDS[COMP_CWORD]}}"
    prev="${{COMP_WORDS[COMP_CWORD-1]}}"
    if [[ $COMP_CWORD -eq 1 ]]; then
        COMPREPLY=( $(compgen -W "{commands}" -- "$cur") )
        return 0
    fi
    case "${{COMP_WORDS[1]}}" in
        show|edit|clip|use|rm|rename|feedback|comment|versions)
            COMPREPLY=( $(compgen -W "$(pdk list 2>/dev/null | awk 'NR>1 {{print $1}}')" -- "$cur") )
            ;;
        *)
            COMPREPLY=()
            ;;
    esac
}}
complete -F _pdk_complete pdk
"""


def zsh_completion() -> str:
    commands = " ".join(f"'{command}:pdk {command}'" for command in COMPLETION_COMMANDS)
    return f"""#compdef pdk
_pdk() {{
  local -a commands prompts
  commands=({commands})
  prompts=(${{(f)"$(pdk list 2>/dev/null | awk 'NR>1 {{print $1}}')"}})
  if (( CURRENT == 2 )); then
    _describe 'command' commands
    return
  fi
  case $words[2] in
    show|edit|clip|use|rm|rename|feedback|comment|versions)
      _describe 'prompt' prompts
      ;;
  esac
}}
_pdk "$@"
"""


def fish_completion() -> str:
    command_lines = "\n".join(
        f"complete -c pdk -f -n '__fish_use_subcommand' -a {command}" for command in COMPLETION_COMMANDS
    )
    prompt_commands = "show edit clip use rm rename feedback comment versions"
    return (
        f"{command_lines}\n"
        f"complete -c pdk -f -n 'contains (commandline -opc)[2] {prompt_commands}' "
        """-a '(pdk list 2>/dev/null | awk "NR>1 {print \\$1}")'\n"""
    )
