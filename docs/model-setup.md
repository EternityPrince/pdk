# Model Setup

Prompt Deck can use local models for generated summaries, audio transcription,
and optional privacy entity detection.

## Summary Model

Generated digests use MLX on Apple Silicon:

```bash
uv sync --extra summary
./scripts/install.sh
pdk digest 1 --generate
```

Resolution order:

1. `PDK_SUMMARY_MODEL_PATH`
2. `PDK_LLM_MODEL_DIR/gemma-3-text-4b-it-4bit`
3. Hugging Face model id fallback

## Audio Model

```bash
uv sync --extra audio
pdk audio --list-models
pdk audio --model large-v3-turbo
```

`AUDIO_WHISPER_MODEL` can point to a configured model name or a local
faster-whisper model path.

## System Check

```bash
pdk doctor --system
```

This reports adapter selection, clipboard commands, `fzf`, model directories,
and installed optional extras.
