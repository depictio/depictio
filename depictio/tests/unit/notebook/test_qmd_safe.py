"""The helpers that keep request and author text inert in a Quarto document."""

from __future__ import annotations

import ast

import pytest

from depictio.notebook.qmd_safe import (
    ZWSP,
    comment,
    defuse,
    defuse_code,
    esc,
    lines,
    one_line,
    typst_str,
)

# Every terminator ``str.splitlines`` knows, besides "\n".
TERMINATORS = ["\r", "\r\n", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", " ", " "]


@pytest.mark.parametrize("term", TERMINATORS)
def test_a_comment_ends_on_no_terminator_python_does_not_see(term):
    src = comment(f"label{term}import os; os.system('x')")
    for line in src.splitlines():
        assert line.startswith("#"), repr(line)
    tree = ast.parse(src + "\nx = 1")
    assert [type(n).__name__ for n in tree.body] == ["Assign"]


@pytest.mark.parametrize("term", TERMINATORS)
def test_one_line_and_lines_agree_with_splitlines(term):
    text = f"a{term}b"
    assert lines(text) == ["a", "b"]
    assert one_line(text) == "a b"


def test_esc_leaves_no_backtick_brace_or_tag():
    out = esc("`{python} 1` {{< env X >}} <b>\r# h")
    for ch in "`{}<\r\n":
        assert ch not in out
    assert out.startswith("&#96;&#123;python&#125;")


def test_defuse_breaks_every_construct_and_keeps_the_rest():
    text = (
        "**bold** and `code` and {{name}} and {{param:K}}\n"
        "`{python} 6*7`\n"
        "```{python}\nprint(1)\n```\n"
        "~~~ {r}\nx\n~~~\n"
        "{{< env SECRET >}} {{{< include /etc/hostname >}}} {{% x %}}\n"
        "```{=html}\n<b>raw</b>\n```"
    )
    out = defuse(text)
    assert "{{<" not in out and "{{{<" not in out and "{{%" not in out
    assert "`{" not in out and "```{" not in out and "~~~ {" not in out
    # Everything else is the author's markdown, unchanged.
    assert "**bold** and `code` and {{name}} and {{param:K}}" in out
    assert out.replace(ZWSP, "") == text


def test_defuse_keeps_the_generator_raw_blocks_when_asked():
    assert defuse("````{=typst}\n#x\n````", allow_raw=True) == "````{=typst}\n#x\n````"
    assert "````{=typst}" not in defuse("````{=typst}\n#x\n````")


@pytest.mark.parametrize("term", ["\r", " ", "\x85"])
def test_defuse_turns_every_terminator_into_a_newline(term):
    assert defuse(f"a{term}```{{python}}") == f"a\n```{ZWSP}{{python}}"


def test_defuse_code_keeps_the_value_and_drops_the_shortcode():
    src = "s = '{{< env SECRET >}}'  # {{< include x >}}\x0b!rm"
    out = defuse_code(src)
    assert "{{<" not in out and "\x0b" not in out
    scope: dict = {}
    exec(out, scope)  # noqa: S102 - a literal assignment
    assert scope["s"] == "{{< env SECRET >}}"


def test_typst_str_keeps_placeholders_and_escapes_the_rest():
    out = typst_str('a"b\\c {{name}} {{< env X >}} `x`\r\nz')
    assert "{{name}}" in out
    assert "{{<" not in out and "`" not in out and "\r" not in out and "\n" not in out
    assert out.startswith('"a\\"b\\\\c ')
