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
pdk browse
```

`pdk list` prints a compact catalog table with prompt names, tags, use counts, edit counts, feedback counts, and last-used time. It intentionally omits prompt body previews so the list stays useful as an inventory.

Inside `pdk browse`:

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
p  print full prompt body
c  copy full prompt body with pbcopy
e  edit prompt in $EDITOR
f  add feedback in $EDITOR
t  add/remove tags with +tag and -tag
v  show previous versions
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
