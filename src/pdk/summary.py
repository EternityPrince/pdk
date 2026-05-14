from __future__ import annotations

from .model_loader import load_mlx_model, resolve_summary_model

DEFAULT_SUMMARY_MODEL = "mlx-community/gemma-3-text-4b-it-4bit"
SUMMARY_PROMPT_VERSION = "gemma3-4b-ru-v1"


class SummaryModelError(Exception):
    pass


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
    resolved_model = resolve_summary_model(model_name)
    try:
        model, tokenizer = load_mlx_model(resolved_model)
    except RuntimeError as exc:
        raise SummaryModelError(str(exc)) from exc
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
