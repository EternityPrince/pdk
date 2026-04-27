# pmpt

`pmpt` is a small global prompt store for the shell.

```bash
pmpt add review < review_prompt.txt
pbpaste | pmpt add review
pmpt add review
pmpt add review --tag work --tag review
pmpt add review --replace < new_review_prompt.txt
pmpt edit review
pmpt show review | pbcopy
```

Project-local prompts:

```bash
cd my-project
pmpt project init
pmpt add review --tag project < project_review_prompt.txt
pmpt show review
pmpt project status
pmpt --scope global show review
```

By default `pmpt` uses `--scope auto`: inside a folder with `.pmpt/`, or any nested folder below it, commands use `.pmpt/prompts.sqlite3`. Outside a project, commands use the global prompt store. Use `--scope global` or `--scope project` to force one side.

Useful navigation and history commands:

```bash
pmpt list --tag study
pmpt find essay --tag school
pmpt tags
pmpt tag add review work important
pmpt tag rm review important
pmpt stats
pmpt usage
pmpt versions review
pmpt versions review --show 1
pmpt versions review --prune --yes
pmpt feedback review < feedback.txt
pmpt feedback review --list
pmpt browse
```

Inside `pmpt browse`:

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

`pmpt show` keeps stdout clean for pipes. UI text, statuses, questions, and editor prompts go to stderr or the terminal.

Internally, `pmpt` is split into small layers:

- `models.py`: pydantic domain models and enums;
- `database.py`: SQLite connection and schema setup;
- `project.py`: global/project scope resolution;
- `store.py`: prompt repository/service operations;
- `editor.py`: terminal-safe editor integration;
- `interactive.py`: browser workflow;
- `ui.py`: colored output and prompt formatting;
- `cli.py`: argparse command wiring.
