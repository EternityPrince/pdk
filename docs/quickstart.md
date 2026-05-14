# Prompt Deck Quickstart

Prompt Deck is a local shell kit for reusable prompts, safe context packages,
and indexed file digests.

## Install For Development

```bash
uv sync --dev
uv run pdk --help
```

For local model-assisted summaries, create `.env` from `.env.example`, adjust
`PDK_LLM_MODEL_DIR`, then run:

```bash
./scripts/install.sh
```

## First Prompt

```bash
pdk add review --tag work < review.md
pdk list
pdk show review
pdk clip review
```

## First Project Context

```bash
pdk project init
pdk session init
pdk session build sport
pdk show review --context
```

## Health Check

```bash
pdk doctor
pdk doctor --system
```
