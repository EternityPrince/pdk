from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path
import re
import tomllib
from typing import Any, Iterable


class PrivacyConfigError(Exception):
    pass


class PrivacyModelError(Exception):
    pass


@dataclass(frozen=True)
class PrivatePattern:
    name: str
    label: str
    regex: str
    score: float = 0.8
    detector: str = "regex"
    flags: int = 0

    def compile(self) -> re.Pattern[str]:
        try:
            return re.compile(self.regex, self.flags)
        except re.error as exc:
            raise PrivacyConfigError(f"invalid privacy regex for {self.name}: {exc}") from exc


@dataclass(frozen=True)
class PrivateFinding:
    name: str
    label: str
    start: int
    end: int
    text: str
    score: float
    detector: str


DEFAULT_MODEL_BACKEND = "transformers"
DEFAULT_MODEL_NAME = "Gherman/bert-base-NER-Russian"
DEFAULT_MODEL_THRESHOLD = 0.6

MODEL_LABEL_MAP = {
    "PER": ("ml_person", "person name"),
    "PERSON": ("ml_person", "person name"),
    "ORG": ("ml_organization", "organization"),
    "ORGANIZATION": ("ml_organization", "organization"),
    "LOC": ("ml_location", "location"),
    "LOCATION": ("ml_location", "location"),
}


BUILTIN_PATTERNS: tuple[PrivatePattern, ...] = (
    PrivatePattern("openai_api_key", "OpenAI API key", r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    PrivatePattern("github_token", "GitHub token", r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    PrivatePattern("aws_access_key", "AWS access key", r"\bAKIA[0-9A-Z]{16}\b"),
    PrivatePattern("jwt", "JWT token", r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", score=0.75),
    PrivatePattern("private_key_block", "private key block", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    PrivatePattern(
        "secret_assignment",
        "secret assignment",
        r"\b(api[_-]?key|secret|token|password|passwd|pwd)\b\s*[:=]\s*['\"]?[^'\"\s]{8,}",
        flags=re.IGNORECASE,
    ),
    PrivatePattern(
        "email",
        "email address",
        r"\b[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+\b",
        score=0.85,
    ),
    PrivatePattern(
        "ru_phone",
        "Russian phone number",
        r"(?<!\w)(?:\+?7|8)[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}(?!\w)",
        score=0.8,
    ),
    PrivatePattern(
        "ru_full_name",
        "Russian full name",
        r"\b(?:фио|имя|клиент|заказчик|контакт)\s*[:=-]\s*[А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+){1,2}\b",
        score=0.7,
        flags=re.IGNORECASE,
    ),
    PrivatePattern(
        "ru_address",
        "Russian address",
        r"\bадрес\s*[:=-]\s*[А-ЯЁA-Z0-9][^\n,;]*(?:ул\.?|улица|проспект|пр-т|дом|д\.|кв\.|квартира)[^\n;]*",
        score=0.7,
        flags=re.IGNORECASE,
    ),
    PrivatePattern(
        "ru_passport",
        "Russian passport",
        r"\b(?:паспорт(?:\s*(?:рф|серия|номер|№))?|серия\s+и\s+номер)\s*[:№#-]?\s*\d{2}\s?\d{2}\s?\d{6}\b",
        score=0.85,
        flags=re.IGNORECASE,
    ),
    PrivatePattern(
        "ru_snils",
        "Russian SNILS",
        r"\b\d{3}[-\s]?\d{3}[-\s]?\d{3}[-\s]?\d{2}\b",
        score=0.65,
    ),
    PrivatePattern(
        "ru_inn",
        "Russian INN",
        r"\bинн\s*[:№#-]?\s*\d{10}(?:\d{2})?\b",
        score=0.85,
        flags=re.IGNORECASE,
    ),
    PrivatePattern(
        "bank_card",
        "bank card number",
        r"\b(?:\d[ -]*?){13,19}\b",
        score=0.6,
    ),
)


PRIVACY_CONFIG_TEMPLATE = """# Prompt Deck privacy config
# Put custom private-data regexes here. This global config applies everywhere.
# Built-ins stay enabled unless listed in [privacy].disabled.

[privacy]
disabled = []

[model]
enabled = false
backend = "transformers"
model = "Gherman/bert-base-NER-Russian"
threshold = 0.6

[[patterns]]
name = "contract_number"
label = "Contract number"
regex = "\\\\bcontract-[0-9]{4,}\\\\b"
score = 0.7
ignore_case = true

[profiles.client_a]
disabled = []

[[profiles.client_a.patterns]]
name = "client_ticket"
label = "Client A ticket"
regex = "\\\\bCA-[0-9]{5,}\\\\b"
score = 0.75
"""


def _default_home() -> Path:
    env_home = os.environ.get("PDK_HOME") or os.environ.get("PMPT_HOME")
    if env_home:
        return Path(env_home).expanduser()
    support_dir = Path.home() / "Library" / "Application Support"
    legacy_home = support_dir / "pmpt"
    home = support_dir / "Prompt Deck"
    if legacy_home.exists() and not home.exists():
        return legacy_home
    return home


def _nearest_project_config(cwd: Path | None = None) -> Path | None:
    current = (cwd or Path.cwd()).resolve()
    for path in (current, *current.parents):
        config = path / ".pdk" / "privacy.toml"
        if config.exists():
            return config
        legacy_config = path / ".pmpt" / "privacy.toml"
        if legacy_config.exists():
            return legacy_config
    return None


def privacy_config_paths(cwd: Path | None = None) -> list[Path]:
    explicit = os.environ.get("PDK_PRIVACY_CONFIG")
    if explicit:
        return [Path(value).expanduser() for value in explicit.split(os.pathsep) if value]
    paths = [_default_home() / "privacy.toml"]
    project_config = _nearest_project_config(cwd)
    if project_config is not None:
        paths.append(project_config)
    return paths


def default_privacy_config_path() -> Path:
    return _default_home() / "privacy.toml"


def project_privacy_config_path(cwd: Path | None = None) -> Path:
    current = (cwd or Path.cwd()).resolve()
    for path in (current, *current.parents):
        project_dir = path / ".pdk"
        if project_dir.is_dir():
            return project_dir / "privacy.toml"
        legacy_project_dir = path / ".pmpt"
        if legacy_project_dir.is_dir():
            return legacy_project_dir / "privacy.toml"
    raise PrivacyConfigError("project is not initialized; run `pdk project init`")


def _as_list(value: Any, *, field: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise PrivacyConfigError(f"privacy config field {field} must be a list")
    return value


def _pattern_from_config(raw: Any, *, path: Path) -> PrivatePattern:
    if not isinstance(raw, dict):
        raise PrivacyConfigError(f"privacy pattern in {path} must be a table")
    name = raw.get("name")
    regex = raw.get("regex")
    if not isinstance(name, str) or not name.strip():
        raise PrivacyConfigError(f"privacy pattern in {path} is missing name")
    if not isinstance(regex, str) or not regex:
        raise PrivacyConfigError(f"privacy pattern {name} in {path} is missing regex")
    label = raw.get("label", name)
    if not isinstance(label, str):
        raise PrivacyConfigError(f"privacy pattern {name} label must be a string")
    score = raw.get("score", 0.8)
    if not isinstance(score, int | float):
        raise PrivacyConfigError(f"privacy pattern {name} score must be a number")
    flags = re.IGNORECASE if raw.get("ignore_case", False) else 0
    return PrivatePattern(
        name=name.strip(),
        label=label.strip() or name.strip(),
        regex=regex,
        score=float(score),
        detector=f"regex:{path}",
        flags=flags,
    )


def _model_table(config: dict[str, Any], path: Path, profile: str | None) -> dict[str, Any]:
    table: dict[str, Any] = {}
    raw = config.get("model", {})
    if raw:
        if not isinstance(raw, dict):
            raise PrivacyConfigError(f"model section in {path} must be a table")
        table.update(raw)
    profile_table = _profile_table(config, path, profile)
    raw_profile_model = profile_table.get("model", {}) if profile_table else {}
    if raw_profile_model:
        if not isinstance(raw_profile_model, dict):
            raise PrivacyConfigError(f"model section for privacy profile {profile} in {path} must be a table")
        table.update(raw_profile_model)
    return table


def load_model_config(paths: Iterable[Path] | None = None, *, profile: str | None = None) -> dict[str, Any]:
    config_values: dict[str, Any] = {
        "enabled": False,
        "backend": DEFAULT_MODEL_BACKEND,
        "model": DEFAULT_MODEL_NAME,
        "threshold": DEFAULT_MODEL_THRESHOLD,
    }
    for path in paths or privacy_config_paths():
        if not path.exists():
            continue
        config_values.update(_model_table(_load_config(path), path, profile))
    enabled = config_values.get("enabled", False)
    if not isinstance(enabled, bool):
        raise PrivacyConfigError("model.enabled must be a boolean")
    backend = config_values.get("backend", DEFAULT_MODEL_BACKEND)
    model = config_values.get("model", DEFAULT_MODEL_NAME)
    threshold = config_values.get("threshold", DEFAULT_MODEL_THRESHOLD)
    if backend != "transformers":
        raise PrivacyConfigError(f"unsupported privacy model backend: {backend}")
    if not isinstance(model, str) or not model.strip():
        raise PrivacyConfigError("model.model must be a string")
    if not isinstance(threshold, int | float):
        raise PrivacyConfigError("model.threshold must be a number")
    return {
        "enabled": enabled,
        "backend": backend,
        "model": model.strip(),
        "threshold": float(threshold),
    }


def _load_config(path: Path) -> dict[str, Any]:
    try:
        config = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise PrivacyConfigError(f"invalid privacy config {path}: {exc}") from exc
    if not isinstance(config, dict):
        raise PrivacyConfigError(f"privacy config {path} must be a table")
    return config


def _privacy_table(config: dict[str, Any], path: Path) -> dict[str, Any]:
    privacy = config.get("privacy", {})
    if privacy and not isinstance(privacy, dict):
        raise PrivacyConfigError(f"privacy section in {path} must be a table")
    return privacy if isinstance(privacy, dict) else {}


def _profile_table(config: dict[str, Any], path: Path, profile: str | None) -> dict[str, Any]:
    if profile is None:
        return {}
    profiles = config.get("profiles", {})
    if not profiles:
        return {}
    if not isinstance(profiles, dict):
        raise PrivacyConfigError(f"profiles section in {path} must be a table")
    raw = profiles.get(profile, {})
    if not raw:
        return {}
    if not isinstance(raw, dict):
        raise PrivacyConfigError(f"privacy profile {profile} in {path} must be a table")
    return raw


def _model_label(raw_label: str) -> tuple[str, str]:
    normalized = raw_label.removeprefix("B-").removeprefix("I-").upper()
    mapped = MODEL_LABEL_MAP.get(normalized)
    if mapped is not None:
        return mapped
    label = "ml_" + re.sub(r"[^a-z0-9]+", "_", normalized.lower()).strip("_")
    return label or "ml_entity", normalized.lower() or "entity"


@lru_cache(maxsize=4)
def _transformers_pipeline(model_name: str):
    try:
        from transformers import pipeline
    except ModuleNotFoundError as exc:
        raise PrivacyModelError("ML privacy detection requires installing the `ml` extra") from exc
    return pipeline(
        "token-classification",
        model=model_name,
        tokenizer=model_name,
        aggregation_strategy="simple",
    )


def _model_findings(
    text: str,
    *,
    model_name: str,
    threshold: float,
) -> list[PrivateFinding]:
    try:
        entities = _transformers_pipeline(model_name)(text)
    except Exception as exc:
        if isinstance(exc, PrivacyModelError):
            raise
        raise PrivacyModelError(f"privacy model failed: {exc}") from exc
    findings: list[PrivateFinding] = []
    for entity in entities:
        score = float(entity.get("score", 0.0))
        if score < threshold:
            continue
        start = entity.get("start")
        end = entity.get("end")
        if not isinstance(start, int) or not isinstance(end, int):
            continue
        raw_label = str(entity.get("entity_group") or entity.get("entity") or "entity")
        name, label = _model_label(raw_label)
        findings.append(
            PrivateFinding(
                name=name,
                label=label,
                start=start,
                end=end,
                text=text[start:end],
                score=score,
                detector=f"transformers:{model_name}",
            )
        )
    return findings


def _extend_from_table(
    patterns: list[PrivatePattern],
    disabled: set[str],
    table: dict[str, Any],
    *,
    path: Path,
    disabled_field: str,
    patterns_field: str,
) -> None:
    for name in _as_list(table.get("disabled"), field=disabled_field):
        if not isinstance(name, str):
            raise PrivacyConfigError(f"{disabled_field} entries in {path} must be strings")
        disabled.add(name)
    patterns.extend(
        _pattern_from_config(item, path=path) for item in _as_list(table.get("patterns"), field=patterns_field)
    )


def load_private_patterns(paths: Iterable[Path] | None = None, *, profile: str | None = None) -> list[PrivatePattern]:
    patterns = list(BUILTIN_PATTERNS)
    disabled: set[str] = set()
    for path in paths or privacy_config_paths():
        if not path.exists():
            continue
        config = _load_config(path)
        _extend_from_table(
            patterns,
            disabled,
            _privacy_table(config, path),
            path=path,
            disabled_field="privacy.disabled",
            patterns_field="privacy.patterns",
        )
        _extend_from_table(
            patterns,
            disabled,
            config,
            path=path,
            disabled_field="disabled",
            patterns_field="patterns",
        )
        if profile:
            _extend_from_table(
                patterns,
                disabled,
                _profile_table(config, path, profile),
                path=path,
                disabled_field=f"profiles.{profile}.disabled",
                patterns_field=f"profiles.{profile}.patterns",
            )
    return [pattern for pattern in patterns if pattern.name not in disabled]


def privacy_profiles(paths: Iterable[Path] | None = None) -> list[str]:
    names: set[str] = set()
    for path in paths or privacy_config_paths():
        if not path.exists():
            continue
        config = _load_config(path)
        profiles = config.get("profiles", {})
        if profiles and not isinstance(profiles, dict):
            raise PrivacyConfigError(f"profiles section in {path} must be a table")
        if isinstance(profiles, dict):
            names.update(name for name, value in profiles.items() if isinstance(name, str) and isinstance(value, dict))
    return sorted(names)


def _better_finding(candidate: PrivateFinding, current: PrivateFinding) -> PrivateFinding:
    candidate_key = (candidate.score, candidate.end - candidate.start)
    current_key = (current.score, current.end - current.start)
    return candidate if candidate_key > current_key else current


def _merge_overlaps(findings: list[PrivateFinding]) -> list[PrivateFinding]:
    ordered = sorted(findings, key=lambda item: (item.start, item.end))
    merged: list[PrivateFinding] = []
    for finding in ordered:
        if not merged or finding.start >= merged[-1].end:
            merged.append(finding)
            continue
        merged[-1] = _better_finding(finding, merged[-1])
    return merged


def detect_private_data(
    text: str,
    patterns: Iterable[PrivatePattern] | None = None,
    *,
    profile: str | None = None,
    use_model: bool = False,
    model_name: str | None = None,
    model_threshold: float | None = None,
) -> list[PrivateFinding]:
    findings: list[PrivateFinding] = []
    for pattern in patterns or load_private_patterns(profile=profile):
        compiled = pattern.compile()
        for match in compiled.finditer(text):
            findings.append(
                PrivateFinding(
                    name=pattern.name,
                    label=pattern.label,
                    start=match.start(),
                    end=match.end(),
                    text=match.group(0),
                    score=pattern.score,
                    detector=pattern.detector,
                )
            )
    model_config = load_model_config(profile=profile)
    model_enabled = use_model or bool(model_config["enabled"])
    if model_enabled:
        findings.extend(
            _model_findings(
                text,
                model_name=model_name or str(model_config["model"]),
                threshold=model_threshold if model_threshold is not None else float(model_config["threshold"]),
            )
        )
    return _merge_overlaps(findings)


def private_warning_labels(text: str, *, profile: str | None = None, use_model: bool = False) -> list[str]:
    labels = {finding.label for finding in detect_private_data(text, profile=profile, use_model=use_model)}
    return sorted(labels)


def placeholder_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").upper() or "PRIVATE"


def mask_value(value: str) -> str:
    if len(value) <= 4:
        return "*" * len(value)
    return value[:2] + ("*" * max(3, len(value) - 4)) + value[-2:]


def redact_private_data(
    text: str,
    *,
    mode: str = "placeholder",
    profile: str | None = None,
    use_model: bool = False,
    model_name: str | None = None,
    model_threshold: float | None = None,
) -> str:
    findings = detect_private_data(
        text,
        profile=profile,
        use_model=use_model,
        model_name=model_name,
        model_threshold=model_threshold,
    )
    replacements: dict[tuple[str, str], str] = {}
    counters: dict[str, int] = {}
    if mode == "placeholder":
        for finding in findings:
            key = (finding.name, finding.text)
            if key not in replacements:
                counters[finding.name] = counters.get(finding.name, 0) + 1
                replacements[key] = f"<{placeholder_name(finding.name)}_{counters[finding.name]}>"
    redacted = text
    for finding in reversed(findings):
        if mode == "redact":
            replacement = "[REDACTED]"
        elif mode == "mask":
            replacement = mask_value(finding.text)
        else:
            replacement = replacements[(finding.name, finding.text)]
        redacted = redacted[: finding.start] + replacement + redacted[finding.end :]
    return redacted
