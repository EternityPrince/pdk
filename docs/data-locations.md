# Data Locations

Prompt Deck stores data locally.

## Prompt Stores

- Global store: `~/Library/Application Support/Prompt Deck/prompts.sqlite3` on macOS unless `PDK_HOME` is set.
- Project store: `.pdk/prompts.sqlite3` inside an initialized project.
- Scope selection: `--scope auto` uses a project store when `.pdk/` is found, otherwise the global store.

## File Index

The file index is a separate SQLite database named `index.sqlite3` in the Prompt
Deck application support directory. It stores extracted text chunks, token
counts, privacy findings, entities, and summaries.

## Config Files

- `.pdk/context.toml`: project context and session module configuration.
- `.pdk/session.md`: last built session context.
- Global `privacy.toml`: default private-data rules and optional ML model config.
- Project `.pdk/privacy.toml`: project-local privacy config when present.

## Environment

- `.env`: local, ignored by git.
- `.env.example`: safe template tracked by git.
- `PDK_HOME`: override Prompt Deck application data location.
- `PDK_DISABLE_ANALYTICS=1`: disable local command usage logging.
