from __future__ import annotations

from functools import lru_cache
import re

try:
    import tiktoken
except ModuleNotFoundError:  # pragma: no cover - exercised when global tool deps are stale
    tiktoken = None

DEFAULT_ENCODING = "o200k_base"
_FALLBACK_TOKEN_PATTERN = re.compile(r"\w+|[^\w\s]", re.UNICODE)


@lru_cache(maxsize=1)
def _encoding():
    if tiktoken is None:
        return None
    return tiktoken.get_encoding(DEFAULT_ENCODING)


def has_exact_tokenizer() -> bool:
    return _encoding() is not None


def count_tokens(text: str) -> int:
    encoding = _encoding()
    if encoding is not None:
        return len(encoding.encode(text))
    return len(_FALLBACK_TOKEN_PATTERN.findall(text))


def token_summary(template: str, rendered: str | None = None) -> str:
    label = "tokens" if has_exact_tokenizer() else "tokens~"
    template_count = count_tokens(template)
    if rendered is None or rendered == template:
        return f"{label}: {template_count}"
    return f"{label}: template={template_count} rendered={count_tokens(rendered)}"
