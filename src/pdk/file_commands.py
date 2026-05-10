from __future__ import annotations

import argparse
import json
from typing import TextIO

from .command_support import CliError, _detect_for_args, _write_scan_table
from .file_index import FileIndex
from .file_workflows import index_paths
from .sources import read_sources
from .summary import DEFAULT_SUMMARY_MODEL, SUMMARY_PROMPT_VERSION, generate_summary
from .text_analysis import digest_tags, extractive_summary
from .ui import PromptFormatter


def cmd_index(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    if not args.paths:
        raise CliError("index needs at least one file or folder")
    rows = index_paths(
        args.paths,
        recursive=not args.no_recursive,
        chunk_tokens=args.chunk_tokens,
        detector=lambda text: _detect_for_args(args, text),
    )
    _write_scan_table([row.as_table_row() for row in rows], stdout)
    return 0


def cmd_digest(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    index = FileIndex()
    targets = args.targets or [str(file.id) for file in index.files()]
    if not targets:
        raise CliError("nothing is indexed yet; run `pdk index PATH` first")
    model = args.summary_model or DEFAULT_SUMMARY_MODEL
    stdout.write("file\tmodel\tsummary\n")
    for target in targets:
        file = index.get_file(target)
        source = read_sources([file.path])[0]
        findings = _detect_for_args(args, source.text)
        summary = (
            generate_summary(
                source.text,
                model_name=model,
                max_input_chars=args.max_input_chars,
                max_tokens=args.max_output_tokens,
            )
            if args.generate
            else extractive_summary(source.text, max_chars=args.max_chars)
        )
        tags = digest_tags(source.text, findings)
        index.add_summary(
            file.id,
            level="file",
            model=model,
            prompt_version=SUMMARY_PROMPT_VERSION if args.generate else "extractive-v1",
            summary=summary,
            tags_json=json.dumps(tags, ensure_ascii=False),
        )
        stdout.write(f"{file.path}\t{model}\t{PromptFormatter.preview(summary, 120)}\n")
    return 0


def cmd_files(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    stdout.write("id\tfindings\ttokens\tstatus\tpath\n")
    for file in FileIndex().files():
        stdout.write(f"{file.id}\t{file.finding_count}\t{file.token_count}\t{file.status}\t{file.path}\n")
    return 0


def cmd_file_show(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    try:
        file = FileIndex().get_file(args.target)
    except KeyError as exc:
        raise CliError(f"indexed file not found: {args.target}") from exc
    stdout.write(f"id\t{file.id}\n")
    stdout.write(f"path\t{file.path}\n")
    stdout.write(f"kind\t{file.kind}\n")
    stdout.write(f"size_bytes\t{file.size_bytes}\n")
    stdout.write(f"sha256\t{file.sha256}\n")
    stdout.write(f"indexed_at\t{file.indexed_at}\n")
    stdout.write(f"tokens\t{file.token_count}\n")
    stdout.write(f"lines\t{file.line_count}\n")
    stdout.write(f"characters\t{file.char_count}\n")
    stdout.write(f"findings\t{file.finding_count}\n")
    if file.summary:
        stdout.write(f"summary\t{file.summary}\n")
    return 0


def cmd_file_entities(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    index = FileIndex()
    try:
        rows = index.entities(args.target)
    except KeyError as exc:
        raise CliError(f"indexed file not found: {args.target}") from exc
    stdout.write("entity\tcount\tsource\tvalue\n")
    for row in rows:
        value = row["display_value"] if args.show_values else "[hidden]"
        stdout.write(f"{row['entity_type']}\t{row['count']}\t{row['source']}\t{value}\n")
    return 0
