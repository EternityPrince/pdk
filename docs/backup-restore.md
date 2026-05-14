# Backup And Restore

Use JSON export for round-trip backup and import.

```bash
pdk export --format json --output backup.json
pdk import backup.json
```

## Scope

By default, export follows the active project selection. Use explicit scope
flags when backing up:

```bash
pdk export --all --format json --output all-prompts.json
pdk export --project client-a --format json --output client-a.json
pdk export --no-project --format json --output unbound.json
```

## Dry Run And Replace

```bash
pdk import backup.json --dry-run
pdk import backup.json --replace
```

## Redaction

Exports may contain secrets or private data. Use `--redact` when the artifact
will leave your machine:

```bash
pdk export --format json --redact --output redacted-backup.json
```
