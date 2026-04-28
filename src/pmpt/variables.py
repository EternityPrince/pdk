from __future__ import annotations

from typing import TextIO

from .editor import TextEditor
from .templating import find_variables, render_template


class VariableFillCancelled(Exception):
    pass


class VariablePrompter:
    def __init__(self, editor: TextEditor, stdin: TextIO, stderr: TextIO, *, color: str) -> None:
        self._editor = editor
        self._stdin = stdin
        self._stderr = stderr

    def fill(self, body: str) -> str:
        names = find_variables(body)
        if not names:
            return body

        edited = self._editor.edit(self._form(names))
        values = self._parse_form(edited, names)
        return render_template(body, values)

    def _form(self, names: list[str]) -> str:
        lines = [
            "# pdk variable form",
            "# Fill values between the BEGIN/END marker lines.",
            "# Marker lines are not included in the final prompt.",
            "# Values are inserted literally; nested {{...}} is not re-interpreted.",
            "",
        ]
        for name in names:
            lines.extend([self._begin(name), "", self._end(name), ""])
        return "\n".join(lines)

    def _parse_form(self, text: str, names: list[str]) -> dict[str, str]:
        lines = text.splitlines(keepends=True)
        values: dict[str, str] = {}

        for name in names:
            begin = self._begin(name)
            end = self._end(name)
            value_lines: list[str] = []
            inside = False

            for line in lines:
                marker = line.strip()
                if marker == begin:
                    inside = True
                    value_lines = []
                    continue
                if inside and marker == end:
                    values[name] = self._clean_value("".join(value_lines))
                    inside = False
                    break
                if inside:
                    value_lines.append(line)

            values.setdefault(name, "")

        return values

    def _clean_value(self, value: str) -> str:
        if value.endswith("\n"):
            return value[:-1]
        return value

    def _begin(self, name: str) -> str:
        return f"--- pdk begin {{{{{name}}}}} ---"

    def _end(self, name: str) -> str:
        return f"--- pdk end {{{{{name}}}}} ---"
