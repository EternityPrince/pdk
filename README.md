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

Token counts use the `o200k_base` tokenizer. `pdk show NAME` keeps stdout clean for pipes and writes token stats to stderr instead. For prompts with variables, the stderr line includes both the template token count and the rendered token count after values are filled:

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
e           edit prompt in $EDITOR
t           add/remove tags with +tag and -tag
v           show previous versions
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
