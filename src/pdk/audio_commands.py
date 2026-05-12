from __future__ import annotations

import argparse
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TextIO

from .command_support import CliError, _reporter
from .interactive import Clipboard
from .project import ProjectNotFoundError, ProjectResolver
from .session_config import load_session_config


DEFAULT_AUDIO_MODEL_NAME = "large-v3-turbo"
SAMPLE_RATE = 16_000


@dataclass(frozen=True)
class AudioModel:
    name: str
    path: Path
    description: str


AUDIO_MODELS: dict[str, AudioModel] = {
    "large-v3-turbo": AudioModel(
        name="large-v3-turbo",
        path=Path("/Users/vladimirkasterin/models/audio/faster-whisper-large-v3-turbo"),
        description="Local faster-whisper Large v3 Turbo model.",
    ),
}


def default_audio_model() -> str:
    return os.environ.get("AUDIO_WHISPER_MODEL", DEFAULT_AUDIO_MODEL_NAME)


def resolve_audio_model(value: str | Path) -> AudioModel:
    raw = str(value)
    if raw in AUDIO_MODELS:
        return AUDIO_MODELS[raw]
    path = Path(raw).expanduser()
    return AudioModel(
        name=path.name or raw,
        path=path,
        description="Custom faster-whisper model path.",
    )


def record_until_enter(stdin: TextIO, stderr: TextIO) -> object:
    try:
        import numpy as np
        import sounddevice as sd
    except ImportError as exc:
        raise CliError("missing audio dependencies; install with `uv sync --extra audio`") from exc

    chunks = []

    def on_audio(indata, _frames, _time, status) -> None:
        if status:
            print(status, file=stderr)
        chunks.append(indata.copy())

    try:
        stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            callback=on_audio,
        )
    except sd.PortAudioError as exc:
        raise CliError(f"could not open microphone: {exc}") from exc

    try:
        with stream:
            stdin.readline()
    except KeyboardInterrupt:
        print(file=stderr)

    if not chunks:
        raise CliError("no audio was recorded")

    return np.concatenate(chunks, axis=0).reshape(-1)


def transcribe_audio(
    audio,
    model: AudioModel,
    *,
    device: str,
    compute_type: str,
    language: str | None,
) -> str:
    try:
        import ctranslate2
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise CliError("missing transcription dependencies; install with `uv sync --extra audio`") from exc

    if not model.path.exists():
        raise CliError(f"model directory does not exist for {model.name}: {model.path}")

    ctranslate2.set_log_level(logging.ERROR)
    whisper = WhisperModel(
        str(model.path),
        device=device,
        compute_type=compute_type,
        local_files_only=True,
    )
    segments, _info = whisper.transcribe(
        audio,
        language=language,
        vad_filter=True,
        beam_size=5,
    )
    return " ".join(segment.text.strip() for segment in segments).strip()


def _session_module_file(module_name: str, filename: str) -> Path:
    try:
        context = ProjectResolver().resolve("project")
    except ProjectNotFoundError as exc:
        raise CliError("audio --module requires a project; run `pdk session init` first") from exc
    if context.project_root is None:
        raise CliError("audio --module requires a project; run `pdk session init` first")

    config = load_session_config(context.project_root)
    module = next((candidate for candidate in config.modules if candidate.name == module_name), None)
    if module is None:
        raise CliError(f"unknown session module: {module_name}")
    if not module.dirs:
        raise CliError(f"session module has no directory target: {module_name}")

    base = Path(module.dirs[0]).expanduser()
    directory = base if base.is_absolute() else context.project_root / base
    return directory / filename


def _target_path(args: argparse.Namespace) -> Path | None:
    if args.module:
        return _session_module_file(args.module, args.context_file)
    if args.append:
        path = Path(args.append).expanduser()
        return path if path.is_absolute() else Path.cwd() / path
    return None


def _entry_text(text: str, *, timestamp: bool) -> str:
    body = " ".join(text.split())
    if not body:
        raise CliError("transcript is empty")
    prefix = f"{datetime.now().strftime('%Y-%m-%d %H:%M')} - " if timestamp else ""
    return f"- {prefix}{body}"


def _heading_line(heading: str) -> str:
    clean = heading.strip().lstrip("#").strip()
    if not clean:
        raise CliError("--heading cannot be empty")
    return f"## {clean}"


def _append_plain(text: str, entry: str) -> str:
    base = text.rstrip()
    return f"{base}\n\n{entry}\n" if base else f"# Inbox\n\n{entry}\n"


def _append_under_heading(text: str, heading: str, entry: str) -> str:
    wanted = _heading_line(heading)
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != wanted:
            continue
        insert_at = len(lines)
        for next_index in range(index + 1, len(lines)):
            if re.match(r"^#{1,2}\s+\S", lines[next_index]):
                insert_at = next_index
                break
        while insert_at > index + 1 and lines[insert_at - 1].strip() == "":
            insert_at -= 1
        inserted = ["", entry] if insert_at < len(lines) and lines[insert_at].strip() == "" else ["", entry, ""]
        lines[insert_at:insert_at] = inserted
        return "\n".join(lines).rstrip() + "\n"

    return _append_plain(text, f"{wanted}\n\n{entry}")


def append_transcript(path: Path, text: str, *, heading: str | None, timestamp: bool) -> None:
    entry = _entry_text(text, timestamp=timestamp)
    path.parent.mkdir(parents=True, exist_ok=True)
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    updated = _append_under_heading(current, heading, entry) if heading else _append_plain(current, entry)
    path.write_text(updated, encoding="utf-8")


def _write_models(stdout: TextIO) -> None:
    stdout.write("name\tpath\tdescription\n")
    for model in AUDIO_MODELS.values():
        stdout.write(f"{model.name}\t{model.path}\t{model.description}\n")


def cmd_audio(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    if args.list_models:
        _write_models(stdout)
        return 0

    model = resolve_audio_model(args.model)
    reporter = _reporter(args, stderr)
    text = args.text
    if text is None:
        print("Recording. Press Enter to stop.", file=stderr)
        audio = record_until_enter(stdin, stderr)
        print(f"Transcribing with {model.name} ({model.path})...", file=stderr)
        text = transcribe_audio(
            audio,
            model,
            device=args.device,
            compute_type=args.compute_type,
            language=args.language,
        )

    if not text.strip():
        raise CliError("transcript is empty")

    target = _target_path(args)
    if target is not None:
        append_transcript(target, text, heading=args.heading, timestamp=not args.no_timestamp)
        reporter.success(f"Appended audio note to {target}")

    if args.copy:
        try:
            copied = Clipboard().copy(text)
        except Exception as exc:
            raise CliError("clipboard command failed") from exc
        if not copied:
            raise CliError("clipboard command is not available")
        reporter.success("Copied transcript")

    if not args.quiet:
        stdout.write(text.rstrip() + "\n")
    return 0
