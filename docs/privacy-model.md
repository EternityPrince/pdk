# Privacy Model

Prompt Deck is local-first. It does not send prompt, context, or indexed file
text to a remote service by default.

## Detection

Regex private-data detection is enabled by default for common values such as
emails, phone numbers, and Russian personal document patterns. Rules are
configured in `privacy.toml`.

```bash
pdk privacy init
pdk privacy list
pdk check --show-spans --stdin < draft.md
pdk redact --stdin < draft.md
```

## Profiles

Profiles let one global config hold project-specific patterns:

```bash
pdk check --profile client_a --stdin < draft.md
pdk context --redact --privacy-profile client_a
```

## Optional ML Detection

ML entity detection is opt-in:

```bash
uv sync --extra ml
pdk check --model --show-spans --stdin < draft.md
```

## Local Command Usage Log

`pdk stats use` is powered by local `command_usage_events` rows in the selected
SQLite store. It records command variant, status, timestamp, and terse error
details. Disable it with:

```bash
PDK_DISABLE_ANALYTICS=1 pdk show review
```
