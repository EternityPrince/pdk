from __future__ import annotations

from functools import lru_cache


DEFAULT_SUMMARY_MODEL = "mlx-community/gemma-3-text-4b-it-4bit"
SUMMARY_PROMPT_VERSION = "gemma3-4b-ru-v1"


class SummaryModelError(Exception):
    pass


@lru_cache(maxsize=2)
def _load_mlx_model(model_name: str):
    try:
        from mlx_lm import load
    except ModuleNotFoundError as exc:
        raise SummaryModelError("Gemma digest generation requires installing the `summary` extra") from exc
    return load(model_name)


def _format_prompt(tokenizer, text: str) -> str:
    instruction = (
        "Сделай качественное краткое резюме документа на русском языке.\n"
        "Верни структурированный Markdown:\n"
        "## Кратко\n"
        "2-5 предложений о сути документа.\n\n"
        "## Важное\n"
        "- ключевые факты, обязательства, сроки, суммы или решения\n\n"
        "## Теги\n"
        "- 5-10 коротких тегов\n\n"
        "## Сущности\n"
        "- люди, организации, телефоны, email, документы или идентификаторы, если они есть\n\n"
        "Не выдумывай факты. Если данных нет, напиши `не найдено`.\n\n"
        f"Документ:\n{text}"
    )
    if getattr(tokenizer, "chat_template", None) is not None:
        messages = [{"role": "user", "content": instruction}]
        return tokenizer.apply_chat_template(messages, add_generation_prompt=True)
    return instruction


def generate_summary(
    text: str,
    *,
    model_name: str = DEFAULT_SUMMARY_MODEL,
    max_input_chars: int = 24000,
    max_tokens: int = 900,
) -> str:
    try:
        from mlx_lm import generate
    except ModuleNotFoundError as exc:
        raise SummaryModelError("Gemma digest generation requires installing the `summary` extra") from exc
    model, tokenizer = _load_mlx_model(model_name)
    prompt = _format_prompt(tokenizer, text[:max_input_chars])
    try:
        return generate(
            model,
            tokenizer,
            prompt=prompt,
            max_tokens=max_tokens,
            verbose=False,
        ).strip()
    except Exception as exc:
        raise SummaryModelError(f"Gemma digest generation failed: {exc}") from exc
