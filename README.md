# Prompt Deck

Prompt Deck is a local AI context kit for the shell.

It is built around three everyday workflows:

1. Save reusable prompts.
2. Prepare safe AI context.
3. Index and digest files.

```bash
pdk add review --tag refactor < review.md
pdk project init
pdk session init
pdk session list
pdk session build sport
pdk list
pdk show workout --context
pdk clip workout --context
pdk session build all --dry-run
pdk audio --module work --heading "Inbox"
pdk context client-a
pdk context client-a --file README.md
pdk context client-a --dir src --redact --budget 12000
pdk export --format json --output backup.json
```

## Session context from Markdown folders

`pdk session` is the fast path for a common AI workflow: keep long-lived personal
or project context in thematic Markdown folders, build the relevant context once,
then attach it to any prompt with `pdk show NAME --context`.

Write durable facts in `context/base` and topic folders:

```text
context/
  base/
    profile.md
    preferences.md
    goals.md
  food/
    nutrition.md
  sport/
    training.md
  study/
    learning.md
  work/
    projects.md
```

`base` is for your profile, goals, and preferences. `food`, `sport`, `study`,
and `work` are topic modules. When you build a topic such as `sport`, Prompt Deck
also includes its dependencies such as `base`. By default `session build`
refreshes the file index for the selected modules; use `--no-index` only when
you intentionally want the previously indexed content.

```bash
pdk session init
pdk session list
pdk session build sport
pdk session show
pdk list
pdk show workout --context
pdk clip workout --context
pdk session clear
pdk session build all --dry-run
```

`session build` saves the last built context in project state, and also prints it
to stdout unless you use `--copy` or `--output`. `pdk session show` prints that
saved context later. `pdk show NAME --context` first fills the prompt
placeholders, then appends the saved session context after it; `pdk clip NAME
--context` does the same and copies the result to the clipboard. `pdk session
clear` removes only the saved session state from `.pdk/session.md`. Use
`--dry-run` to see modules, files, token estimate, and budget status without
printing full file text. Use `--budget 12000` to warn when the package is too
large, and `--redact` to mask emails, phone numbers, and other configured
private data before saving or copying.

Session settings live in project-local `.pdk/context.toml`:

```toml
[session]
root = "context"
default_modules = ["base"]
file_detail = "full"
compact = true
budget = 16000
redact = false

[session.modules.base]
description = "General profile, goals, and preferences"
dirs = ["context/base"]

[session.modules.sport]
description = "Training, activity, and recovery"
dirs = ["context/sport"]
depends_on = ["base"]
```

`pdk context` is the lower-level, universal context builder for prompts, notes,
explicit indexed files, directories, profiles, JSON output, and custom filters.
`pdk session` is the product workflow on top: thematic Markdown folders saved as
the current project session state. `pdk export` is different again: it is for
backup and import, not the daily AI session payload.

## Voice capture into context

`pdk audio` records from the microphone until Enter is pressed, transcribes the
audio with a local faster-whisper model, and prints the transcript. Use model
names instead of long paths:

```bash
pdk audio --list-models
pdk audio --model large-v3-turbo
```

To turn a quick spoken thought into durable session context, append it as a
Markdown bullet:

```bash
pdk audio --module work --heading "Inbox"
pdk audio --append context/base/goals.md --heading "Current goals"
```

`--module work` writes to `context/work/inbox.md` by default. Set
`AUDIO_WHISPER_MODEL` to either a configured model name or a custom local
faster-whisper model path. Install audio dependencies with:

```bash
uv sync --extra audio
```

Project profiles live in `.pdk/context.toml`. A profile can describe the whole
context package, or split it into named modules so the rendered context shows
which indexed files belong together and how those modules relate:

```toml
[context.default]
dirs = ["docs"]
files = ["README.md"]
file_detail = "summary"
compact = true

[[context.default.modules]]
name = "runtime"
description = "CLI entrypoints and command orchestration"
dirs = ["src/pdk"]
include = ["*.py"]
exclude = ["*_commands.py"]
depends_on = ["storage"]

[[context.default.modules]]
name = "storage"
dirs = ["src/pdk"]
include = ["database.py", "store.py", "file_index.py"]
```

## Quick Reference

```bash
pdk add review < review_prompt.txt
pbpaste | pdk add review
pdk add review
pdk add review --tag work --tag review
pdk add review --replace < new_review_prompt.txt
pdk edit review
pdk show review | pbcopy
pdk scan
pdk scan docs/
pdk project init
pdk session init
pdk session list
pdk session build sport
pdk show workout --context
pdk audio --module work --heading "Inbox"
pdk index README.md
pdk index docs/
pdk digest
pdk digest --generate
pdk context --profile default --copy
pdk context --profile default --compact --copy
pdk tokens
pdk check
pdk check --show-spans
pdk check --profile client_a
pdk check --stdin < draft.md
pdk redact --stdin < draft.md
pdk privacy init
pdk clip review
pdk use review
pdk browse --fzf
pdk completions zsh > ~/.zfunc/_pdk
```

Project-local prompts:

```bash
cd my-project
pdk project init
pdk add review --tag project < project_review_prompt.txt
pdk show review
pdk project status
pdk --scope global show review
```

By default `pdk` uses `--scope auto`: inside a folder with `.pdk/`, or any nested folder below it, commands use `.pdk/prompts.sqlite3`. Outside a project, commands use the global prompt store. Use `--scope global` or `--scope project` to force one side.

Named projects live inside whichever store `--scope` selects:

```bash
pdk project create client-a "Client A launch"
pdk project use client-a
pdk add launch-review < review.md
pdk list
pdk add general-template --no-project < template.md
pdk project assign client-a existing-prompt
pdk project unassign existing-prompt
pdk project clear
```

Prompts can belong to one named project or stay unbound. `pdk add`, `list`, `find`, `browse`, `stats`, and `export` use the active named project when one is set. Pass `--project NAME` for a one-command override or `--no-project` for unbound prompts.

Notes are unbound by default, even when a project is active:

```bash
pdk note add "Things to remember"
pdk note add "Launch notes" --project client-a
pdk note list --project client-a
pdk note show 1
pdk note edit 1
pdk note versions 1
```

AI context is the command you use during daily work:

```bash
pdk session build sport
pdk show workout --context
pdk clip workout --context
pdk session build all --dry-run
pdk context client-a
pdk context client-a --file README.md
pdk context client-a --dir src --redact --budget 12000
pdk context --profile default --copy
```

Backup and round-trip import/export stay separate:

```bash
pdk export --format json --output backup.json
pdk import backup.json
pdk security status
PDK_PASSPHRASE='...' pdk security lock
PDK_PASSPHRASE='...' pdk security unlock
```

Useful navigation and history commands:

```bash
pdk list --tag study
pdk find essay --tag school
pdk tags
pdk tag add review work important
pdk tag rm review important
pdk stats
pdk usage
pdk doctor
pdk duplicates
pdk stale --days 30
pdk rename old-name new-name
pdk move review --project client-a
pdk move shared-template --no-project
pdk versions review
pdk versions review --show 1
pdk versions review --prune --yes
pdk feedback review < feedback.txt
pdk feedback review --list
pdk comment review < comment.txt
pdk browse
pdk browse --plain
```

`pdk list` prints a compact catalog table with prompt names, token counts, tags, use counts, edit counts, feedback counts, and last-used time. It intentionally omits prompt body previews so the list stays useful as an inventory.

Token counts use the `o200k_base` tokenizer. `pdk tokens` is the fastest
clipboard counter: with no arguments it reads the current clipboard and prints
only the token count. Use `pdk tok` as a short alias, or `--details` when you
want the source and tokenizer too.

```bash
pdk tokens
pdk tok
pdk tokens --stdin < prompt.md
pdk tokens draft.md --details
```

`pdk scan` is the easiest privacy entry point: with no arguments it scans the clipboard, and with files or folders it scans those sources and prints a compact table of findings, tokens, lines, characters, and detected private-data types.

```bash
pdk scan
pdk scan draft.md notes.docx book.epub
pdk scan docs/
pdk scan --details --profile client_a docs/
```

`pdk check` prints detailed stats for one source. It reads the clipboard by default and prints token count plus text stats such as characters, bytes, lines, words, and private-data warnings. Use `--show-spans` to list detected private-data spans without printing the raw private values. You can pass a file directly, or use `--stdin`/`--file` when you want to be explicit.

```bash
pdk check
pdk check draft.md
pdk check --show-spans
```

`pdk redact` is the quick replacement command. With no arguments it reads the clipboard and writes redacted text to stdout; with a file it redacts that file's extracted text.

```bash
pdk redact
pdk redact draft.md
pdk redact --mode mask --stdin < draft.md
```

File scanning reads plain text-like files and DOCX directly. PDF and EPUB extraction use higher-quality optional readers:

```bash
pip install 'prompt-deck[files]'
pdk scan report.pdf book.epub
```

For reusable document work, `pdk index` stores extracted file metadata, chunks, privacy findings, entities, and summaries in a global SQLite database:

```bash
pdk index docs/
pdk files
pdk file show 1
pdk file entities 1
pdk digest 1
pdk digest 1 --generate
```

The file index lives in the Prompt Deck application support directory as `index.sqlite3`. Files are tracked by path, size, mtime, SHA-256, extractor version, chunks, token counts, privacy findings, aggregated entities, and summaries. `pdk digest` stores a fast extractive summary by default. Use `--generate` to run a local Gemma 3 4B summary model through MLX:

```bash
pip install 'prompt-deck[summary]'
pdk digest 1 --generate
```

The default summary model is `mlx-community/gemma-3-text-4b-it-4bit`, an MLX 4-bit conversion for text generation. The original Google model is `google/gemma-3-4b-it`; Google describes Gemma 3 4B as instruction-tuned, multilingual, and suitable for summarization with a 128K token context window for 4B models.

Private-data detection is regex-based by default and can be customized in one global `privacy.toml`. You do not need to initialize a folder to use it:

```bash
pdk privacy init
pdk privacy path
pdk privacy list
pdk privacy profiles
pdk privacy model
pdk redact --stdin < draft.md
```

Top-level patterns apply everywhere. Profiles let you keep project-specific rules in the same global config and opt into them with `--profile` or `--project`:

```toml
[[patterns]]
name = "contract_number"
label = "Contract number"
regex = "\\bcontract-[0-9]{4,}\\b"
score = 0.7
ignore_case = true

[profiles.client_a]
disabled = []

[[profiles.client_a.patterns]]
name = "client_ticket"
label = "Client A ticket"
regex = "\\bCA-[0-9]{5,}\\b"
score = 0.75
```

Optional ML entity recognition can be enabled per command, or in the global config:

```bash
pdk check --model --show-spans
pdk redact --model --stdin < draft.md
pdk check --model --model-threshold 0.75 --stdin < draft.md
```

```toml
[model]
enabled = false
backend = "transformers"
model = "Gherman/bert-base-NER-Russian"
threshold = 0.6
```

The default ML backend is a Hugging Face `transformers` token-classification pipeline using `Gherman/bert-base-NER-Russian`, a Russian NER model. Install the optional dependencies before using `--model`:

```bash
pip install 'prompt-deck[ml]'
```

Regex detection remains the first pass. The ML detector adds span-based findings for entities such as people, organizations, and locations, and overlapping findings keep the higher-confidence match.

`pdk show NAME` keeps stdout clean for pipes and writes token stats to stderr instead. For prompts with variables, the stderr line includes both the template token count and the rendered token count after values are filled:

```bash
pdk show letter | pbcopy
# stderr: tokens: template=42 rendered=118
```

`pdk browse` opens a fullscreen terminal UI when stdin/stdout are attached to a terminal. If it is run through pipes, captured output, or with `--plain`, it uses the original line-based browser.

Inside fullscreen `pdk browse`:

```text
/           focus search
#tag        type in search and press Enter to toggle a tag filter
Esc         clear search text
Enter/c     copy the selected prompt
f           fill variables in $EDITOR, then copy
x           copy the current filtered list as Markdown context
e           edit prompt in $EDITOR
t           add/remove tags with +tag and -tag
v           show previous versions
s           cycle sort by name, tokens, uses, updated
?           show help
q           quit
```

Inside `pdk browse --plain`:

```text
text        search by name, body, or tag
/text       search explicitly
#tag        filter by tag
tags        show tag aggregation
/           clear filters
number      open a prompt
```

Prompt actions inside the browser:

```text
enter/o  show full prompt body again
c  copy full prompt body with pbcopy
cf fill variables, then copy the rendered prompt
e  edit prompt in $EDITOR
f  add feedback in $EDITOR
t  add/remove tags with +tag and -tag
v  show previous versions
print  print full prompt body
n/p  next or previous prompt in the active list
b  back to list
q  quit
```

`pdk show` keeps stdout clean for pipes. UI text, statuses, questions, and editor prompts go to stderr or the terminal.

If a prompt contains variables such as `{{topic}}` or `{{text}}`, `pdk show NAME` opens one `$EDITOR` form that lists every variable as a visible section:

```text
--- pdk begin {{text}} ---
Write the value here.
--- pdk end {{text}} ---
```

Text between the marker lines is inserted literally. This keeps `stdout` clean while making the required variables visible inside the editor itself.

Internally, Prompt Deck is split into small layers:

- `models.py`: pydantic domain models and enums;
- `database.py`: SQLite connection and schema setup;
- `project.py`: global/project scope resolution;
- `store.py`: prompt repository/service operations;
- `editor.py`: terminal-safe editor integration;
- `interactive.py`: browser workflow;
- `ui.py`: colored output and prompt formatting;
- `variables.py`: editor form for filling prompt variables;
- `cli.py`: argparse command wiring.
