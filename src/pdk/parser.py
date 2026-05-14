from __future__ import annotations

import argparse

from .audio_commands import DEFAULT_AUDIO_MODEL_NAME, default_audio_model
from .commands import (
    cmd_audio,
    cmd_add,
    cmd_edit,
    cmd_show,
    cmd_scan,
    cmd_index,
    cmd_digest,
    cmd_files,
    cmd_file_show,
    cmd_file_entities,
    cmd_check,
    cmd_tokens,
    cmd_redact,
    cmd_clip,
    cmd_list,
    cmd_find,
    cmd_tags,
    cmd_tag_add,
    cmd_tag_rm,
    cmd_stats,
    cmd_usage,
    cmd_doctor,
    cmd_duplicates,
    cmd_stale,
    cmd_rename,
    cmd_move,
    cmd_versions,
    cmd_feedback,
    cmd_browse,
    cmd_project_create,
    cmd_project_list,
    cmd_project_show,
    cmd_project_rename,
    cmd_project_describe,
    cmd_project_edit,
    cmd_project_use,
    cmd_project_clear,
    cmd_project_assign,
    cmd_project_unassign,
    cmd_project_init,
    cmd_project_status,
    cmd_privacy_path,
    cmd_privacy_init,
    cmd_privacy_list,
    cmd_privacy_model,
    cmd_privacy_profiles,
    cmd_note_add,
    cmd_note_list,
    cmd_note_show,
    cmd_note_edit,
    cmd_note_versions,
    cmd_export,
    cmd_import,
    cmd_security_status,
    cmd_security_lock,
    cmd_security_unlock,
    cmd_completions,
    cmd_context,
    cmd_session_build,
    cmd_session_clear,
    cmd_session_init,
    cmd_session_list,
    cmd_session_show,
    cmd_rm,
)
from .summary import DEFAULT_SUMMARY_MODEL

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdk",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Prompt Deck is a local AI context kit.\n"
            "Save reusable prompts, prepare safe AI context, and index/digest files from your shell."
        ),
        epilog="""
Workflows:
  1. Save reusable prompts
  2. Prepare safe AI context
  3. Index and digest files

Quick examples:
  pdk add review --tag refactor < review.md
  pdk project init
  pdk index README.md
  pdk digest README.md
  pdk session build sport
  pdk show workout --context
  pdk context client-a
  pdk context client-a --file README.md
  pdk context client-a --dir src --redact --budget 12000
  pdk context --profile default --copy
  pdk context --profile default --compact --copy
  pdk tokens
  pdk export --format json --output backup.json
  pdk import backup.json

Session vs context vs backup:
  `pdk session` builds and saves the last Markdown context from modules such as
  base, food, sport, study, and work.
  `pdk show NAME --context` appends that saved session after filling prompt placeholders.
  `pdk context` is the lower-level builder for prompts, notes, indexed files,
  directories, profiles, JSON output, and custom filters.
  `pdk export` is for backup and round-trip import/export.

How scope and projects fit together:
  --scope chooses the database first. In auto mode, pdk uses .pdk/prompts.sqlite3
  when you are inside an initialized folder; otherwise it uses the global store.
  Named projects live inside that selected database. Use --project for one command,
  --no-project for unbound prompts/notes, and `pdk project clear` to stop filtering
  by the active named project.

Examples:
  pdk session build sport
  pdk show workout --context
  pdk context client-a --dir src --redact --budget 12000
  pdk browse --query review

Run `pdk COMMAND --help` for command-specific examples.
""",
    )
    parser.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help="colorize UI output",
    )
    parser.add_argument(
        "--scope",
        choices=("auto", "global", "project"),
        default="auto",
        help="choose prompt store; auto uses .pdk when present",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    _register_audio_commands(subparsers)
    _register_prompt_core_commands(subparsers)
    _register_scan_commands(subparsers)
    _register_file_commands(subparsers)
    _register_text_safety_commands(subparsers)
    _register_prompt_library_commands(subparsers)
    _register_stats_commands(subparsers)
    _register_prompt_hygiene_commands(subparsers)
    _register_project_commands(subparsers)
    _register_privacy_commands(subparsers)
    _register_note_commands(subparsers)
    _register_transfer_commands(subparsers)
    _register_context_session_commands(subparsers)
    _register_security_commands(subparsers)
    _register_completion_commands(subparsers)
    _register_remove_commands(subparsers)
    return parser


def _register_audio_commands(subparsers) -> None:
    audio = subparsers.add_parser(
        "audio",
        help="record speech and transcribe it into text",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Record microphone audio, transcribe it with a local faster-whisper model, "
            "and optionally append the transcript as a Markdown bullet."
        ),
        epilog=f"""
Examples:
  pdk audio
  pdk audio --model {DEFAULT_AUDIO_MODEL_NAME}
  pdk audio --module work --heading "Decisions"
  pdk audio --append context/base/goals.md --heading "Current goals"
  pdk audio --list-models

Model names:
  Use --list-models to see configured names and paths. AUDIO_WHISPER_MODEL can
  contain either a configured name or a custom local model path.
""",
    )
    audio.add_argument("--model", default=default_audio_model(), help="model name from --list-models or local path")
    audio.add_argument("--list-models", action="store_true", help="list configured local Whisper models")
    audio.add_argument(
        "--device",
        default="auto",
        choices=("auto", "cpu", "cuda"),
        help="device used by faster-whisper",
    )
    audio.add_argument(
        "--compute-type",
        default="float32",
        help="faster-whisper compute type, for example float32, int8, float16",
    )
    audio.add_argument("--language", help="language code hint for Whisper, for example ru or en")
    audio.add_argument("--copy", action="store_true", help="copy transcript to the clipboard")
    audio.add_argument("--quiet", action="store_true", help="do not print transcript to stdout")
    audio.add_argument("--text", help="skip recording and use this text as the transcript")
    audio_target = audio.add_mutually_exclusive_group()
    audio_target.add_argument("--append", help="append transcript as a Markdown bullet to this file")
    audio_target.add_argument("--module", help="append transcript to a session module inbox file")
    audio.add_argument("--context-file", default="inbox.md", help="module file used with --module")
    audio.add_argument("--heading", help="Markdown section heading to append under")
    audio.add_argument("--no-timestamp", action="store_true", help="append the bullet without a timestamp")
    audio.set_defaults(func=cmd_audio)

def _register_prompt_core_commands(subparsers) -> None:
    add = subparsers.add_parser(
        "add",
        help="save a prompt",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Save a prompt body from stdin, or open $EDITOR when stdin is empty.",
        epilog="""
Examples:
  pdk add review < review.md
  pbpaste | pdk add rewrite --tag writing
  pdk add review --replace < better-review.md
  pdk add launch-review --project client-a < review.md
  pdk add shared-template --no-project < template.md

Project behavior:
  If a named project is active, `pdk add NAME` saves into it.
  Use --project for a one-command override, or --no-project for a shared prompt.
""",
    )
    add.add_argument("name")
    add.add_argument("--replace", action="store_true", help="replace an existing prompt")
    add.add_argument("--tag", action="append", help="attach a tag; repeat or use comma-separated tags")
    add.add_argument("--project", help="assign the prompt to a named project")
    add.add_argument("--no-project", action="store_true", help="save as an unbound prompt")
    add.set_defaults(func=cmd_add)

    edit = subparsers.add_parser("edit", help="edit an existing prompt")
    edit.add_argument("name")
    edit.set_defaults(func=cmd_edit)

    show = subparsers.add_parser("show", help="print a prompt")
    show.add_argument("name")
    show.add_argument("--context", action="store_true", help="append the last built pdk session context")
    show.set_defaults(func=cmd_show)

def _register_scan_commands(subparsers) -> None:
    scan = subparsers.add_parser(
        "scan",
        help="scan clipboard or files for private data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Scan text for private data. With no input paths, scans the current clipboard.",
        epilog="""
Examples:
  pdk scan
  pdk scan draft.md notes.docx book.epub
  pdk scan docs/
  pdk scan --details --profile client_a docs/
""",
    )
    scan.add_argument("paths", nargs="*", help="files or folders to scan; defaults to clipboard")
    scan.add_argument("--stdin", action="store_true", help="scan stdin instead of the clipboard")
    scan.add_argument("--file", help="scan one UTF-8 text file")
    scan.add_argument("--no-recursive", action="store_true", help="do not recurse into folders")
    scan.add_argument("--profile", help="use a named privacy profile from the global config")
    scan.add_argument("--project", dest="profile", help="alias for --profile")
    scan.add_argument("--model", action="store_true", help="also run the configured ML entity detector")
    scan.add_argument("--model-name", help="override the configured ML model")
    scan.add_argument("--model-threshold", type=float, help="override the ML confidence threshold")
    scan.add_argument("--details", action="store_true", help="show detected spans without raw private values")
    scan.set_defaults(func=cmd_scan)

def _register_file_commands(subparsers) -> None:
    index_cmd = subparsers.add_parser(
        "index",
        help="extract, scan, chunk, and store files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Index files into the global pdk file database for later digest/search workflows.",
        epilog="""
Examples:
  pdk index docs/
  pdk index contract.pdf notes.docx
  pdk files
""",
    )
    index_cmd.add_argument("paths", nargs="+", help="files or folders to index")
    index_cmd.add_argument("--no-recursive", action="store_true", help="do not recurse into folders")
    index_cmd.add_argument("--chunk-tokens", type=int, default=1200, help="target tokens per stored chunk")
    index_cmd.add_argument("--profile", help="use a named privacy profile from the global config")
    index_cmd.add_argument("--project", dest="profile", help="alias for --profile")
    index_cmd.add_argument("--model", action="store_true", help="also run the configured ML entity detector")
    index_cmd.add_argument("--model-name", help="override the configured ML model")
    index_cmd.add_argument("--model-threshold", type=float, help="override the ML confidence threshold")
    index_cmd.set_defaults(func=cmd_index)

    digest = subparsers.add_parser(
        "digest",
        help="summarize indexed files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Create file-level digests in the global file index. The generation backend targets Gemma 3 4B.",
        epilog="""
Examples:
  pdk digest
  pdk digest 12
  pdk digest 12 --generate
  pdk digest /path/to/file.pdf --generate --model mlx-community/gemma-3-text-4b-it-4bit
""",
    )
    digest.add_argument("targets", nargs="*", help="indexed file ids or paths; defaults to all indexed files")
    digest.add_argument("--model", dest="summary_model", default=DEFAULT_SUMMARY_MODEL, help="summary model id")
    digest.add_argument(
        "--generate",
        action="store_true",
        help="run local Gemma generation instead of the fast extractive digest",
    )
    digest.add_argument(
        "--max-chars",
        type=int,
        default=1200,
        help="maximum characters for the current extractive digest",
    )
    digest.add_argument(
        "--max-input-chars",
        type=int,
        default=24000,
        help="maximum input characters sent to the summary model",
    )
    digest.add_argument(
        "--max-output-tokens",
        type=int,
        default=900,
        help="maximum output tokens from the summary model",
    )
    digest.add_argument("--profile", help="use a named privacy profile from the global config")
    digest.add_argument("--project", dest="profile", help="alias for --profile")
    digest.add_argument("--model-name", help="override the configured privacy NER model")
    digest.add_argument("--model-threshold", type=float, help="override the privacy NER threshold")
    digest.set_defaults(func=cmd_digest)

    files = subparsers.add_parser("files", help="list indexed files")
    files.set_defaults(func=cmd_files)

    file_cmd = subparsers.add_parser("file", help="inspect one indexed file")
    file_subparsers = file_cmd.add_subparsers(dest="file_command", required=True)
    file_show = file_subparsers.add_parser("show", help="show indexed file metadata")
    file_show.add_argument("target", help="indexed file id or path")
    file_show.set_defaults(func=cmd_file_show)
    file_entities = file_subparsers.add_parser("entities", help="show aggregated entities for an indexed file")
    file_entities.add_argument("target", help="indexed file id or path")
    file_entities.add_argument("--show-values", action="store_true", help="print raw entity values")
    file_entities.set_defaults(func=cmd_file_entities)

def _register_text_safety_commands(subparsers) -> None:
    check = subparsers.add_parser(
        "check",
        help="inspect token and text stats",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Inspect token count and basic text stats. By default, reads the current clipboard.",
        epilog="""
Examples:
  pdk check
  pdk check --stdin < prompt.md
  pdk check --file prompt.md
""",
    )
    check.add_argument("paths", nargs="*", help="optional single file to inspect")
    check_source = check.add_mutually_exclusive_group()
    check_source.add_argument("--stdin", action="store_true", help="read text from stdin instead of the clipboard")
    check_source.add_argument("--file", help="read text from a UTF-8 file instead of the clipboard")
    check.add_argument("--profile", help="use a named privacy profile from the global config")
    check.add_argument("--project", dest="profile", help="alias for --profile")
    check.add_argument("--model", action="store_true", help="also run the configured ML entity detector")
    check.add_argument("--model-name", help="override the configured ML model")
    check.add_argument("--model-threshold", type=float, help="override the ML confidence threshold")
    check.add_argument("--show-spans", action="store_true", help="show detected private-data spans")
    check.set_defaults(func=cmd_check)

    tokens = subparsers.add_parser(
        "tokens",
        aliases=["tok"],
        help="count tokens in the clipboard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Count tokens quickly. By default, reads the current clipboard and prints only the number.",
        epilog="""
Examples:
  pdk tokens
  pdk tok
  pdk tokens --stdin < prompt.md
  pdk tokens draft.md --details
""",
    )
    tokens.add_argument("paths", nargs="*", help="optional single file to count; defaults to clipboard")
    tokens_source = tokens.add_mutually_exclusive_group()
    tokens_source.add_argument("--stdin", action="store_true", help="read text from stdin instead of the clipboard")
    tokens_source.add_argument("--file", help="read text from a UTF-8 file instead of the clipboard")
    tokens.add_argument("--details", action="store_true", help="show source, tokenizer, and character count")
    tokens.set_defaults(func=cmd_tokens)

    redact = subparsers.add_parser(
        "redact",
        help="replace private data in text",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Replace detected private data. By default, reads the current clipboard and writes redacted text to stdout."
        ),
        epilog="""
Examples:
  pdk redact
  pdk redact --stdin < prompt.md
  pdk redact --mode mask --file prompt.md
""",
    )
    redact.add_argument("paths", nargs="*", help="optional single file to redact")
    redact_source = redact.add_mutually_exclusive_group()
    redact_source.add_argument("--stdin", action="store_true", help="read text from stdin instead of the clipboard")
    redact_source.add_argument("--file", help="read text from a UTF-8 file instead of the clipboard")
    redact.add_argument("--profile", help="use a named privacy profile from the global config")
    redact.add_argument("--project", dest="profile", help="alias for --profile")
    redact.add_argument("--model", action="store_true", help="also run the configured ML entity detector")
    redact.add_argument("--model-name", help="override the configured ML model")
    redact.add_argument("--model-threshold", type=float, help="override the ML confidence threshold")
    redact.add_argument(
        "--mode",
        choices=("placeholder", "mask", "redact"),
        default="placeholder",
        help="replacement strategy",
    )
    redact.set_defaults(func=cmd_redact)

def _register_prompt_library_commands(subparsers) -> None:
    clip = subparsers.add_parser("clip", help="copy a prompt to the clipboard")
    clip.add_argument("name")
    clip.add_argument("--raw", action="store_true", help="copy template text without filling variables")
    clip.add_argument("--context", action="store_true", help="append the last built pdk session context")
    clip.set_defaults(func=cmd_clip)

    use = subparsers.add_parser("use", help="copy a prompt to the clipboard")
    use.add_argument("name")
    use.add_argument("--raw", action="store_true", help="copy template text without filling variables")
    use.set_defaults(func=cmd_clip)

    list_cmd = subparsers.add_parser(
        "list",
        help="scan saved prompts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Show an inventory table with use counts, edit counts, comments, last use, and tags.",
        epilog="""
Examples:
  pdk list
  pdk list --tag work
  pdk list --query review
  pdk list --project client-a
  pdk list --no-project

Tip:
  `list` is for scanning names and metadata. Use `find QUERY` when you want body
  text to participate in search results.
""",
    )
    list_cmd.add_argument("--tag", action="append", help="filter by tag; repeat for all required tags")
    list_cmd.add_argument("--query", help="filter by name, body, or tag text")
    list_cmd.add_argument("--project", help="filter by named project")
    list_cmd.add_argument("--no-project", action="store_true", help="filter unbound prompts")
    list_cmd.set_defaults(func=cmd_list)

    find = subparsers.add_parser(
        "find",
        help="search prompt names, bodies, and tags",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Search prompt names, bodies, and tags, then print compact matching rows.",
        epilog="""
Examples:
  pdk find essay
  pdk find review --tag work
  pdk find launch --project client-a
""",
    )
    find.add_argument("query")
    find.add_argument("--tag", action="append", help="filter by tag; repeat for all required tags")
    find.add_argument("--project", help="filter by named project")
    find.add_argument("--no-project", action="store_true", help="filter unbound prompts")
    find.set_defaults(func=cmd_find)

    tags = subparsers.add_parser("tags", help="show tag aggregation")
    tags.add_argument("--project", help="filter by named project")
    tags.add_argument("--no-project", action="store_true", help="filter unbound prompts")
    tags.set_defaults(func=cmd_tags)

    tag = subparsers.add_parser("tag", help="add or remove tags")
    tag_subparsers = tag.add_subparsers(dest="tag_command", required=True)
    tag_add = tag_subparsers.add_parser("add", help="add tags to a prompt")
    tag_add.add_argument("name")
    tag_add.add_argument("tags", nargs="+")
    tag_add.set_defaults(func=cmd_tag_add)
    tag_rm = tag_subparsers.add_parser("rm", help="remove tags from a prompt")
    tag_rm.add_argument("name")
    tag_rm.add_argument("tags", nargs="+")
    tag_rm.set_defaults(func=cmd_tag_rm)

def _register_stats_commands(subparsers) -> None:
    stats = subparsers.add_parser(
        "stats",
        help="show prompt, command, or memory statistics",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  pdk stats
  pdk stats coach
  pdk stats use
  pdk stats mem
  pdk stats --prompt use
""",
    )
    stats.add_argument("stats_target", nargs="?", help="prompt name, or use/mem for operational stats")
    stats.add_argument("--prompt", dest="prompt_name", help="force prompt stats for a prompt named use or mem")
    stats.add_argument("--limit", type=int, default=50, help="maximum command rows for `stats use`")
    stats.add_argument("--project", help="filter by named project")
    stats.add_argument("--no-project", action="store_true", help="filter unbound prompts")
    stats.set_defaults(func=cmd_stats)

def _register_prompt_hygiene_commands(subparsers) -> None:
    usage = subparsers.add_parser("usage", help="show detailed usage events")
    usage.add_argument("name", nargs="?")
    usage.add_argument("--limit", type=int, default=50)
    usage.add_argument("--project", help="filter by named project")
    usage.add_argument("--no-project", action="store_true", help="filter unbound prompt usage")
    usage.set_defaults(func=cmd_usage)

    doctor = subparsers.add_parser(
        "doctor",
        help="summarize library hygiene signals",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Report prompt counts, untagged/unbound prompts, duplicate groups, and stale prompts.",
        epilog="""
Examples:
  pdk doctor
  pdk doctor --project client-a
  pdk doctor --days 180
""",
    )
    doctor.add_argument("--project", help="check a named project")
    doctor.add_argument("--no-project", action="store_true", help="check unbound prompts and notes")
    doctor.add_argument("--days", type=int, default=90, help="stale threshold in days")
    doctor.set_defaults(func=cmd_doctor)

    duplicates = subparsers.add_parser(
        "duplicates",
        help="find prompts with duplicate bodies",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Find prompts whose bodies match after whitespace folding and case normalization.",
        epilog="""
Examples:
  pdk duplicates
  pdk duplicates --project client-a
""",
    )
    duplicates.add_argument("--project", help="filter by named project")
    duplicates.add_argument("--no-project", action="store_true", help="filter unbound prompts")
    duplicates.set_defaults(func=cmd_duplicates)

    stale = subparsers.add_parser(
        "stale",
        help="find prompts that have not been used recently",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="List prompts whose last show time, or updated time when never shown, is older than the threshold.",
        epilog="""
Examples:
  pdk stale
  pdk stale --days 30
  pdk stale --project client-a
""",
    )
    stale.add_argument("--days", type=int, default=90, help="stale threshold in days")
    stale.add_argument("--project", help="filter by named project")
    stale.add_argument("--no-project", action="store_true", help="filter unbound prompts")
    stale.set_defaults(func=cmd_stale)

    rename = subparsers.add_parser("rename", help="rename a prompt")
    rename.add_argument("old")
    rename.add_argument("new")
    rename.set_defaults(func=cmd_rename)

    move = subparsers.add_parser(
        "move",
        help="move prompts into a project or back to unbound",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  pdk move review rewrite --project client-a
  pdk move shared-template --no-project
""",
    )
    move.add_argument("names", nargs="+")
    move_target = move.add_mutually_exclusive_group(required=True)
    move_target.add_argument("--project", help="destination named project")
    move_target.add_argument("--no-project", action="store_true", help="move prompts to unbound")
    move.set_defaults(func=cmd_move)

    versions = subparsers.add_parser("versions", help="inspect or clean previous prompt versions")
    versions.add_argument("name")
    versions.add_argument("--show", type=int, metavar="ID", help="print a previous version")
    versions.add_argument("--prune", action="store_true", help="delete previous versions")
    versions.add_argument("--yes", action="store_true", help="confirm pruning")
    versions.set_defaults(func=cmd_versions)

    feedback = subparsers.add_parser(
        "feedback",
        help="attach or list comments for a prompt",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Save comments, observations, or evaluation notes against one prompt.",
        epilog="""
Examples:
  pdk feedback review < feedback.md
  pdk feedback review --list

Alias:
  pdk comment review < comment.md
""",
    )
    feedback.add_argument("name")
    feedback.add_argument("--list", action="store_true", help="list existing feedback")
    feedback.set_defaults(func=cmd_feedback)
    comment = subparsers.add_parser("comment", help="alias for feedback")
    comment.add_argument("name")
    comment.add_argument("--list", action="store_true", help="list existing comments")
    comment.set_defaults(func=cmd_feedback)

    browse = subparsers.add_parser(
        "browse",
        help="browse, print, copy, edit, and comment interactively",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Open an interactive prompt browser with search, tag filters, editing, comments, and versions.",
        epilog="""
Examples:
  pdk browse
  pdk browse --query review
  pdk browse --tag work
  pdk browse --project client-a
  pdk browse --plain

Controls:
  / focuses search, #tag toggles tag filters, Enter/c copies, f fills
  variables and copies, e edits, t edits tags, v opens versions, q quits.
""",
    )
    browse.add_argument("--tag", action="append", help="start with a tag filter")
    browse.add_argument("--query", help="start with a text search")
    browse.add_argument("--project", help="filter by named project")
    browse.add_argument("--no-project", action="store_true", help="filter unbound prompts")
    browse.add_argument("--plain", action="store_true", help="use the original line-based browser")
    browse.add_argument("--fzf", action="store_true", help="select with fzf and copy the chosen prompt")
    browse.set_defaults(func=cmd_browse)

def _register_project_commands(subparsers) -> None:
    project = subparsers.add_parser(
        "project",
        help="initialize .pdk stores and manage named projects",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Project has two jobs: initialize filesystem-local .pdk stores, and manage\n"
            "named projects inside whichever database --scope selects."
        ),
        epilog="""
Use cases:
  Create a .pdk database in this repo:
    pdk project init

  See which database pdk is using:
    pdk project status

  Create and activate a named project in the selected database:
    pdk project create client-a "Client A launch"
    pdk project use client-a
    pdk project edit client-a

  Move existing prompts in or out of a named project:
    pdk project assign client-a review rewrite
    pdk project unassign review

  Stop filtering normal commands by the active named project:
    pdk project clear
""",
    )
    project_subparsers = project.add_subparsers(dest="project_command", required=True)
    project_create = project_subparsers.add_parser("create", help="create a named project")
    project_create.add_argument("name")
    project_create.add_argument("description_text", nargs="*", help="optional project description")
    project_create.add_argument("--description", help="project description")
    project_create.set_defaults(func=cmd_project_create)
    project_list = project_subparsers.add_parser("list", help="list named projects")
    project_list.set_defaults(func=cmd_project_list)
    project_show = project_subparsers.add_parser("show", help="show a named project")
    project_show.add_argument("name")
    project_show.set_defaults(func=cmd_project_show)
    project_rename = project_subparsers.add_parser("rename", help="rename a named project")
    project_rename.add_argument("old")
    project_rename.add_argument("new")
    project_rename.set_defaults(func=cmd_project_rename)
    project_describe = project_subparsers.add_parser("describe", help="replace a project description")
    project_describe.add_argument("name")
    project_describe.add_argument("text", nargs="+")
    project_describe.set_defaults(func=cmd_project_describe)
    project_edit = project_subparsers.add_parser("edit", help="edit project name and description")
    project_edit.add_argument("name")
    project_edit.set_defaults(func=cmd_project_edit)
    project_use = project_subparsers.add_parser("use", help="make a named project active")
    project_use.add_argument("name")
    project_use.set_defaults(func=cmd_project_use)
    project_clear = project_subparsers.add_parser("clear", help="clear the active named project")
    project_clear.set_defaults(func=cmd_project_clear)
    project_assign = project_subparsers.add_parser("assign", help="assign prompts to a project")
    project_assign.add_argument("project")
    project_assign.add_argument("prompts", nargs="+")
    project_assign.set_defaults(func=cmd_project_assign)
    project_unassign = project_subparsers.add_parser("unassign", help="remove prompts from named projects")
    project_unassign.add_argument("prompts", nargs="+")
    project_unassign.set_defaults(func=cmd_project_unassign)
    project_init = project_subparsers.add_parser(
        "init",
        help="initialize .pdk in a folder",
        description="Create a local Prompt Deck store plus starter AI context config files.",
    )
    project_init.add_argument("path", nargs="?", help="project folder; defaults to cwd")
    project_init.set_defaults(func=cmd_project_init)
    project_status = project_subparsers.add_parser("status", help="show active prompt store")
    project_status.set_defaults(func=cmd_project_status)

def _register_privacy_commands(subparsers) -> None:
    privacy = subparsers.add_parser(
        "privacy",
        help="manage private-data detection config",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Manage the global private-data detection config. Model detectors can be "
            "added later behind the same finding format."
        ),
        epilog="""
Examples:
  pdk privacy path
  pdk privacy init
  pdk privacy list
  pdk privacy list --profile client_a
  pdk privacy model
  pdk privacy profiles
""",
    )
    privacy_subparsers = privacy.add_subparsers(dest="privacy_command", required=True)
    privacy_path = privacy_subparsers.add_parser("path", help="show privacy config paths")
    privacy_path.set_defaults(func=cmd_privacy_path)
    privacy_init = privacy_subparsers.add_parser("init", help="write a starter privacy config")
    privacy_init.add_argument("--replace", action="store_true", help="replace an existing config")
    privacy_init.set_defaults(func=cmd_privacy_init)
    privacy_list = privacy_subparsers.add_parser("list", help="list active private-data patterns")
    privacy_list.add_argument("--profile", help="include rules from a named privacy profile")
    privacy_list.set_defaults(func=cmd_privacy_list)
    privacy_model = privacy_subparsers.add_parser("model", help="show configured ML entity detector")
    privacy_model.add_argument("--profile", help="show model config for a named privacy profile")
    privacy_model.set_defaults(func=cmd_privacy_model)
    privacy_profile_list = privacy_subparsers.add_parser("profiles", help="list privacy profiles in config")
    privacy_profile_list.set_defaults(func=cmd_privacy_profiles)

def _register_note_commands(subparsers) -> None:
    note = subparsers.add_parser(
        "note",
        help="save and edit context notes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Notes are free-form context. They are unbound by default, even when a named project is active.",
        epilog="""
Examples:
  pdk note add "Decision log"
  pdk note add "Launch facts" --project client-a
  pdk note list
  pdk note list --no-project
  pdk note show 1
  pdk note edit 1
  pdk note versions 1
""",
    )
    note_subparsers = note.add_subparsers(dest="note_command", required=True)
    note_add = note_subparsers.add_parser("add", help="add a note")
    note_add.add_argument("title_text", nargs="*", help="note title")
    note_add.add_argument("--title", help="note title")
    note_add.add_argument("--project", help="bind the note to a named project")
    note_add.set_defaults(func=cmd_note_add)
    note_list = note_subparsers.add_parser("list", help="list notes")
    note_list.add_argument("--project", help="filter by named project")
    note_list.add_argument("--no-project", action="store_true", help="filter unbound notes")
    note_list.set_defaults(func=cmd_note_list)
    note_show = note_subparsers.add_parser("show", help="show a note")
    note_show.add_argument("id", type=int)
    note_show.set_defaults(func=cmd_note_show)
    note_edit = note_subparsers.add_parser("edit", help="edit a note title and body")
    note_edit.add_argument("id", type=int)
    note_edit.set_defaults(func=cmd_note_edit)
    note_versions = note_subparsers.add_parser("versions", help="show note versions")
    note_versions.add_argument("id", type=int)
    note_versions.set_defaults(func=cmd_note_versions)


def _register_transfer_commands(subparsers) -> None:
    export = subparsers.add_parser(
        "export",
        help="write the current context as Markdown",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Export prompts, notes, comments, prompt versions, note versions, and usage history.\n"
            "By default this exports the active named project when one is set; otherwise it exports the whole store."
        ),
        epilog="""
Examples:
  pdk export
  pdk context > context.md
  pdk context client-a > context.md
  pdk export --format json --output deck.json
  pdk import deck.json
  pdk export --project client-a --output context.md
  pdk export --include usage,versions,comments,notes --since 2026-01-01
  pdk export --format json
  pdk export --all
  pdk export --no-project
""",
    )
    export.add_argument("--project", help="export a named project")
    export.add_argument("--all", action="store_true", help="export the entire current store")
    export.add_argument("--no-project", action="store_true", help="export unbound prompts and notes")
    export.add_argument("--include", help="comma-separated sections: usage,versions,comments,notes")
    export.add_argument("--since", help="include dated history from DATE or ISO timestamp")
    export.add_argument("--format", choices=("markdown", "json"), default="markdown", help="export format")
    export.add_argument("--redact", action="store_true", help="mask secret-like values in exported text")
    export.add_argument("--output", help="write Markdown to a file")
    export.set_defaults(func=cmd_export)

    import_cmd = subparsers.add_parser(
        "import",
        help="import prompts, notes, and projects from export output",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Import a Prompt Deck JSON or Markdown export into the selected store.\n"
            "JSON is the canonical round-trip format; Markdown imports prompts, notes, and projects."
        ),
        epilog="""
Examples:
  pdk import deck.json
  pdk import --format json < deck.json
  pdk import --format markdown < context.md
  pdk import deck.json --dry-run
  pdk import deck.json --replace
""",
    )
    import_cmd.add_argument("input", nargs="?", help="file to import; defaults to stdin")
    import_cmd.add_argument("--format", choices=("auto", "json", "markdown"), default="auto", help="input format")
    import_cmd.add_argument("--replace", action="store_true", help="replace existing prompts with matching names")
    import_cmd.add_argument("--dry-run", action="store_true", help="show what would be imported without writing")
    import_cmd.set_defaults(func=cmd_import)

def _register_context_session_commands(subparsers) -> None:
    context = subparsers.add_parser(
        "context",
        help="write the current AI context",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Gather prompts, notes, and comments for an AI session.",
        epilog="""
Examples:
  pdk context > context.md
  pdk context thesis | pbcopy
  pdk context --include notes,comments
  pdk context --profile default --compact --copy
""",
    )
    context.add_argument("project_name", nargs="?", help="named project to export")
    context.add_argument("--project", help="export a named project")
    context.add_argument("--all", action="store_true", help="export the entire current store")
    context.add_argument("--no-project", action="store_true", help="export unbound prompts and notes")
    context.add_argument(
        "--include",
        action="append",
        help="context sections (usage,versions) or file glob include pattern; repeat for file patterns",
    )
    context.add_argument("--since", help="include dated history from DATE or ISO timestamp")
    context.add_argument("--format", choices=("markdown", "json"), default="markdown", help="export format")
    context.add_argument("--profile", help="load context defaults from .pdk/context.toml")
    context.add_argument("--budget", type=int, help="target context token budget")
    context.add_argument("--redact", action="store_true", help="mask secret-like values in exported text")
    context.add_argument("--privacy-profile", help="use a named privacy profile for redaction")
    context.add_argument("--privacy-model", action="store_true", help="also use configured ML privacy detector")
    context.add_argument("--privacy-model-name", help="override privacy ML model name")
    context.add_argument("--privacy-model-threshold", type=float, help="override privacy ML confidence threshold")
    context.add_argument("--copy", action="store_true", help="copy rendered context to the clipboard")
    context.add_argument("--compact", action="store_true", help="render a tighter Markdown context package")
    context.add_argument("--dry-run", action="store_true", help="show context plan and token estimate without output")
    context.add_argument("--output", help="write context to a file")
    context.add_argument("--file", action="append", help="include indexed file id or path; repeat for multiple files")
    context.add_argument("--dir", action="append", help="include already-indexed files under a directory; repeatable")
    context.add_argument("--exclude", action="append", help="file glob exclude pattern; repeatable")
    context.add_argument(
        "--file-detail",
        choices=("summary", "full"),
        default=None,
        help="include file summary or full extracted text",
    )
    context.set_defaults(func=cmd_context)

    session = subparsers.add_parser(
        "session",
        help="build AI context from thematic Markdown folders",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Create, inspect, and build project-local Markdown context modules.\n"
            "Build saves the latest session in .pdk/session.md so `pdk show NAME --context` "
            "or `pdk clip NAME --context` can append it."
        ),
        epilog="""
Examples:
  pdk session init
  pdk session list
  pdk session build sport
  pdk session show
  pdk show workout --context
  pdk clip workout --context
  pdk session clear
  pdk session build all --dry-run
""",
    )
    session_subparsers = session.add_subparsers(dest="session_command", required=True)

    session_init = session_subparsers.add_parser("init", help="create starter session Markdown folders")
    session_init.add_argument("path", nargs="?", help="session context folder; defaults to context")
    session_init.set_defaults(func=cmd_session_init)

    session_list = session_subparsers.add_parser("list", help="list configured session modules")
    session_list.set_defaults(func=cmd_session_list)

    session_show = session_subparsers.add_parser("show", help="print the last built session context")
    session_show.set_defaults(func=cmd_session_show)

    session_clear = session_subparsers.add_parser(
        "clear",
        help="delete the last built session context",
        description="Delete .pdk/session.md without touching .pdk/context.toml or context folders.",
    )
    session_clear.set_defaults(func=cmd_session_clear)

    session_build = session_subparsers.add_parser(
        "build",
        help="build a session Markdown package",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Select session modules, index their Markdown files, render an AI-ready context package, "
            "and save it as the latest project session."
        ),
    )
    session_build.add_argument("modules", nargs="*", help="session module names, or all")
    session_build.add_argument("--copy", action="store_true", help="copy rendered session to the clipboard")
    session_build.add_argument("--output", help="write session Markdown to a file")
    session_build.add_argument("--dry-run", action="store_true", help="show selected modules and token estimate")
    session_build.add_argument("--no-index", action="store_true", help="do not index selected module paths first")
    session_build.add_argument("--budget", type=int, help="target session token budget")
    session_build.add_argument("--redact", action="store_true", help="mask private values in rendered text")
    session_build.add_argument("--compact", action="store_true", help="render a tighter context package")
    session_build.add_argument(
        "--file-detail",
        choices=("summary", "full"),
        default=None,
        help="include file summary or full extracted text; defaults to full",
    )
    session_build.set_defaults(func=cmd_session_build)

def _register_security_commands(subparsers) -> None:
    security = subparsers.add_parser(
        "security",
        help="inspect or encrypt the global prompt store",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Security helpers warn about secret-like text, redact exports, and optionally\n"
            "encrypt the global SQLite store at rest. Project-local stores are not encrypted."
        ),
        epilog="""
Examples:
  pdk security status
  PDK_PASSPHRASE='...' pdk security lock
  PDK_PASSPHRASE='...' pdk security unlock
""",
    )
    security_subparsers = security.add_subparsers(dest="security_command", required=True)
    security_status = security_subparsers.add_parser("status", help="show global store encryption status")
    security_status.set_defaults(func=cmd_security_status)
    security_lock = security_subparsers.add_parser("lock", help="encrypt the global store")
    security_lock.add_argument("--passphrase", help=argparse.SUPPRESS)
    security_lock.set_defaults(func=cmd_security_lock)
    security_unlock = security_subparsers.add_parser("unlock", help="decrypt the global store")
    security_unlock.add_argument("--passphrase", help=argparse.SUPPRESS)
    security_unlock.set_defaults(func=cmd_security_unlock)

def _register_completion_commands(subparsers) -> None:
    completions = subparsers.add_parser(
        "completions",
        help="print shell completion script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  pdk completions bash > ~/.local/share/bash-completion/completions/pdk
  pdk completions zsh > ~/.zfunc/_pdk
  pdk completions fish > ~/.config/fish/completions/pdk.fish
""",
    )
    completions.add_argument("shell", choices=("bash", "zsh", "fish"))
    completions.set_defaults(func=cmd_completions)

def _register_remove_commands(subparsers) -> None:
    rm = subparsers.add_parser("rm", help="remove a prompt")
    rm.add_argument("name")
    rm.add_argument("--yes", action="store_true", help="confirm removal")
    rm.set_defaults(func=cmd_rm)
