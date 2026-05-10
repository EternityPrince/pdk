from __future__ import annotations

import argparse
import os
from typing import TextIO

from .command_support import (
    CliError,
    _detect_for_args,
    _read_text_source,
    _read_text_sources,
    _reporter,
    _write_scan_table,
)
from .file_workflows import summarize_source
from .privacy import (
    PRIVACY_CONFIG_TEMPLATE,
    default_privacy_config_path,
    load_model_config,
    load_private_patterns,
    privacy_config_paths,
    privacy_profiles,
    redact_private_data,
)
from .project import ProjectResolver
from .security import decrypt_database, encrypt_database, is_encrypted_database
from .text_analysis import line_count, word_count
from .tokens import DEFAULT_ENCODING, count_tokens, has_exact_tokenizer


def _security_passphrase(args: argparse.Namespace) -> bytes | None:
    value = getattr(args, "passphrase", None) or None
    if value is None:
        value = os.environ.get("PDK_PASSPHRASE")
    return value.encode("utf-8") if value else None


def cmd_scan(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    sources = _read_text_sources(args, stdin)
    rows = []
    details = []
    for source in sources:
        findings = _detect_for_args(args, source.text)
        rows.append(summarize_source(source, findings).as_table_row())
        for finding in findings:
            details.append((source.label, finding))
    _write_scan_table(rows, stdout)
    if args.details and details:
        stdout.write("\n")
        stdout.write("source\tentity\tstart\tend\tscore\tdetector\tlabel\n")
        for source, finding in details:
            stdout.write(
                f"{source}\t{finding.name}\t{finding.start}\t{finding.end}\t"
                f"{finding.score:.2f}\t{finding.detector}\t{finding.label}\n"
            )
    return 0


def cmd_check(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    source, text = _read_text_source(args, stdin)
    findings = _detect_for_args(args, text)
    warnings = sorted({finding.label for finding in findings})
    tokenizer = DEFAULT_ENCODING if has_exact_tokenizer() else "fallback"
    stdout.write(f"source\t{source}\n")
    stdout.write(f"tokens\t{count_tokens(text)}\n")
    stdout.write(f"tokenizer\t{tokenizer}\n")
    stdout.write(f"characters\t{len(text)}\n")
    stdout.write(f"bytes_utf8\t{len(text.encode('utf-8'))}\n")
    stdout.write(f"lines\t{line_count(text)}\n")
    stdout.write(f"words\t{word_count(text)}\n")
    stdout.write(f"empty\t{'yes' if not text else 'no'}\n")
    stdout.write(f"private_findings\t{len(findings)}\n")
    stdout.write(f"secret_warnings\t{', '.join(warnings) if warnings else '-'}\n")
    if args.show_spans and findings:
        stdout.write("finding\tentity\tstart\tend\tscore\tdetector\tpreview\n")
        for index, finding in enumerate(findings, 1):
            stdout.write(
                f"{index}\t{finding.name}\t{finding.start}\t{finding.end}\t"
                f"{finding.score:.2f}\t{finding.detector}\t{finding.label}\n"
            )
    return 0


def cmd_redact(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    _, text = _read_text_source(args, stdin)
    stdout.write(
        redact_private_data(
            text,
            mode=args.mode,
            profile=args.profile,
            use_model=args.model,
            model_name=args.model_name,
            model_threshold=args.model_threshold,
        )
    )
    return 0


def cmd_privacy_path(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    for path in privacy_config_paths():
        marker = "exists" if path.exists() else "missing"
        stdout.write(f"{marker}\t{path}\n")
    return 0


def cmd_privacy_init(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    path = default_privacy_config_path()
    if path.exists() and not args.replace:
        raise CliError(f"privacy config already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(PRIVACY_CONFIG_TEMPLATE, encoding="utf-8")
    _reporter(args, stderr).success(f"Wrote privacy config {path}")
    return 0


def cmd_privacy_list(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    stdout.write("name\tlabel\tscore\tdetector\n")
    for pattern in load_private_patterns(profile=args.profile):
        stdout.write(f"{pattern.name}\t{pattern.label}\t{pattern.score:.2f}\t{pattern.detector}\n")
    return 0


def cmd_privacy_model(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    config = load_model_config(profile=args.profile)
    stdout.write(f"enabled\t{'yes' if config['enabled'] else 'no'}\n")
    stdout.write(f"backend\t{config['backend']}\n")
    stdout.write(f"model\t{config['model']}\n")
    stdout.write(f"threshold\t{config['threshold']:.2f}\n")
    return 0


def cmd_privacy_profiles(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    for name in privacy_profiles():
        stdout.write(f"{name}\n")
    return 0


def cmd_security_status(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    path = ProjectResolver().resolve("global").database_path
    stdout.write(f"database\t{path}\n")
    stdout.write(f"encrypted\t{'yes' if is_encrypted_database(path) else 'no'}\n")
    return 0


def cmd_security_lock(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    path = ProjectResolver().resolve("global").database_path
    encrypt_database(path, passphrase=_security_passphrase(args))
    _reporter(args, stderr).success(f"Encrypted global store at {path}")
    return 0


def cmd_security_unlock(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    path = ProjectResolver().resolve("global").database_path
    decrypt_database(path, passphrase=_security_passphrase(args))
    _reporter(args, stderr).success(f"Decrypted global store at {path}")
    return 0
