# Prompt Deck

`pdk` is a small global prompt store for the shell.

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
pdk index docs/
pdk digest
pdk digest --generate
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

Markdown export includes prompts, notes, comments, previous versions, and usage history:

```bash
pdk export
pdk context client-a > context.md
pdk export --all
pdk export --no-project
pdk export --format json --output deck.json
pdk export --redact > safe-context.md
pdk import deck.json
pdk import context.md --format markdown
pdk import deck.json --dry-run
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

Token counts use the `o200k_base` tokenizer. `pdk scan` is the easiest privacy entry point: with no arguments it scans the clipboard, and with files or folders it scans those sources and prints a compact table of findings, tokens, lines, characters, and detected private-data types.

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
