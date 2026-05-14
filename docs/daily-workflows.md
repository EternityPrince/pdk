# Daily Workflows

## Reusable Prompts

```bash
pdk add review --tag refactor < review.md
pdk edit review
pdk show review
pdk clip review
pdk browse
```

Use tags and projects to keep prompt libraries navigable:

```bash
pdk tag add review work
pdk project create client-a "Client A work"
pdk move review --project client-a
```

## Session Context

Use `pdk session` when context lives in thematic Markdown folders:

```bash
pdk session init
pdk session build work
pdk session show
pdk clip review --context
```

## File Index And Digest

Use `pdk index` when files should be reusable across context builds:

```bash
pdk index docs/
pdk files
pdk digest
pdk context --dir docs --file-detail summary
```

## Hygiene

```bash
pdk doctor
pdk duplicates
pdk stale --days 30
pdk stats use
pdk stats mem
```
