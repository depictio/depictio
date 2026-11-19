"""Text that reaches a Quarto document, made inert.

A ``.qmd`` is not only markup: Quarto *runs* parts of it. Anything a dashboard
author, a dataset or an export request can put into the document must not be
able to reach one of these, or rendering the report executes it on the worker
(and, for a downloaded ``.qmd``, on the reader's machine):

* a fenced chunk, ```` ```{python} ````, anywhere in the markdown;
* an inline expression, `` `{python} expr` ``, even inside raw HTML;
* a shortcode, ``{{< env NAME >}}`` / ``{{< include path >}}``, expanded in
  prose, raw HTML and typst blocks, code blocks, cell *source* (a Python
  string literal included) and cell output;
* a line terminator other than ``\\n`` in a ``# comment`` line: Python, IPython's
  line transforms and Quarto's own line-oriented regexes do not agree on what
  ends a line (``str.splitlines`` alone knows eight), so a lone ``\\r`` or
  ``\\u2028`` turns the rest of a comment into code.

Quarto reads all of these from the *source text*, before pandoc parses it: an
HTML entity (``&#123;``) or a zero-width space between the two braces is enough
to keep it from seeing one, while the reader still sees the character.

Every helper here is the one way its context is written; the generator and the
kernel-side components both use them. ``defuse`` and ``defuse_code`` are also
applied to every cell of the document as it is assembled (``cells.render_qmd``),
so a site that forgets its escaping still cannot produce a live construct.

Pure Python, no server imports: the reader's kernel imports it too.
"""

from __future__ import annotations

import html
import re
from typing import Any

ZWSP = "​"

# Every character ``str.splitlines()`` ends a line on (``\r\n`` first, as one).
_TERMINATORS = re.compile(r"\r\n|[\r\n\v\f\x1c\x1d\x1e\x85  ]")
_NOT_NEWLINE = re.compile(r"[\r\v\f\x1c\x1d\x1e\x85  ]")

# Characters an HTML entity keeps away from Quarto's source scan.
_ENTITIES = str.maketrans({"`": "&#96;", "{": "&#123;", "}": "&#125;"})

# Any brace followed by another: what is left of a shortcode once ``<`` is an
# entity.
_BRACE_PAIR = re.compile(r"\{(?=\{)")
_CLOSE_PAIR = re.compile(r"\}(?=\})")
# A shortcode opens with two (or more, the escaped form) braces and ``<``; ``%``
# is accepted too, as Hugo writes them, and blanks before either.
_SHORTCODE_OPEN = re.compile(r"\{\{+(?=[ \t]*[<%])")
# A backtick run (inline code or a fence) or a tilde fence followed by a brace:
# an inline expression (`` `{python} x` ``) or an executable chunk.
_TICK_BRACE = re.compile(r"(`+|~{3,})([ \t]*)\{")
# The same, letting a raw block through (```` ```{=typst} ````, `` `x`{=html} ``):
# the generator writes those itself.
_TICK_BRACE_CODE = re.compile(r"(`+|~{3,})([ \t]*)\{(?!=)")


def normalise_newlines(text: str) -> str:
    """Every line terminator as ``\\n``: one notion of a line for everyone."""
    return _TERMINATORS.sub("\n", text)


def one_line(text: str) -> str:
    """``text`` on one line: each terminator becomes a space."""
    return _TERMINATORS.sub(" ", text)


def lines(text: str) -> list[str]:
    """``text`` split on every terminator ``str.splitlines`` knows."""
    return _TERMINATORS.split(text)


def esc(value: Any, quote: bool = True, *, multiline: bool = False) -> str:
    """``value`` as HTML text: escaped, and with no backtick or brace left.

    For anything dynamic put into prose, a heading, a caption, an attribute or
    raw HTML. Entities rather than the characters: the reader sees the same
    text, Quarto's source scan sees no construct. One line unless
    ``multiline`` (a ``<pre>``), so a label cannot start a new markdown block.
    """
    text = "" if value is None else str(value)
    text = normalise_newlines(text) if multiline else one_line(text)
    return html.escape(text, quote=quote).translate(_ENTITIES)


def meta_text(value: Any) -> str:
    """``value`` for the front matter (a title, an author): escaped, inert.

    Not ``esc``: Quarto resolves shortcodes in metadata *after* pandoc has
    decoded its entities, so a brace written ``&#123;`` is a brace again
    there. The shortcode is broken by a zero-width space instead, which
    survives the decoding; a backtick is still an entity (inline expressions
    are read from the source). A closing pair is broken too: Quarto 1.9 fails
    the whole render on a title holding ``>}}`` alone.
    """
    # ``<`` only: a tag is what pandoc would keep raw; ``&`` stays readable.
    text = one_line("" if value is None else str(value)).replace("<", "&lt;")
    text = _CLOSE_PAIR.sub("}" + ZWSP, _BRACE_PAIR.sub("{" + ZWSP, text))
    return text.replace("`", "&#96;")


def _break_braces(m: re.Match[str]) -> str:
    return ZWSP.join(m.group(0))


def defuse(text: str, *, allow_raw: bool = False) -> str:
    """Markdown with every Quarto construct broken, everything else kept.

    For an author's own markdown (a text tile, a caption, a description): its
    emphasis, lists, links and inline code still render, while a chunk fence,
    an inline expression or a shortcode is shown as the text it is. A
    zero-width space goes between the characters that would form one; inside
    a code span an entity would print as written, the space prints as nothing.

    ``allow_raw`` keeps ```` ```{=format} ```` raw blocks: only for markdown the
    generator itself writes.
    """
    text = normalise_newlines(text)
    text = _SHORTCODE_OPEN.sub(_break_braces, text)
    pattern = _TICK_BRACE_CODE if allow_raw else _TICK_BRACE
    return pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}{ZWSP}{{", text)


def defuse_code(source: str) -> str:
    """Python source as Quarto must see it: no shortcode, no stray line end.

    Shortcodes are expanded in a cell's source before it runs, inside string
    literals too; ``{\\x7b<`` is the same string to Python and no shortcode to
    Quarto. ``repr`` never writes a raw terminator other than ``\\n``, so one
    can only come from text pasted into a comment: it becomes a space.
    """
    source = source.replace("\r\n", "\n")
    source = _NOT_NEWLINE.sub(" ", source)
    return _SHORTCODE_OPEN.sub(lambda m: "{" + "\\x7b" * (len(m.group(0)) - 1), source)


def comment(text: str) -> str:
    """``text`` as ``# `` comment lines, split on every terminator."""
    return "\n".join(f"# {line}" if line else "#" for line in lines(text))


def typst_str(value: Any) -> str:
    """A typst string literal, on one line, holding no Quarto construct.

    Braces stay as they are (a text tile's ``{{name}}`` placeholders are filled
    in these strings when the document runs); a shortcode's opening brace and
    every backtick are written as typst escapes instead.
    """
    s = one_line(str(value)).replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\u{60}")
    return '"' + _SHORTCODE_OPEN.sub(lambda m: "{" + "\\u{7b}" * (len(m.group(0)) - 1), s) + '"'


# ── What the kernel prints ─────────────────────────────────────────────────────
#
# Quarto expands shortcodes in a cell's *output* as well: a title or a data
# value a tile prints (its HTML, its plain-text repr, a figure's labels, a text
# tile's markdown) would read an environment variable, or fail the render with
# a shortcode it cannot resolve. Inline expressions, includes and chunks are
# not read from output, so the shortcode is the one thing to break there.


def _defuse_text(text: str) -> str:
    return _SHORTCODE_OPEN.sub(_break_braces, text) if "{{" in text else text


def defuse_output(value: Any) -> Any:
    """A display bundle (or any JSON value) with no shortcode in its strings."""
    if isinstance(value, str):
        return _defuse_text(value)
    if isinstance(value, dict):
        return {k: defuse_output(v) for k, v in value.items()}
    if isinstance(value, list):
        return [defuse_output(v) for v in value]
    return value


def inert_outputs() -> bool:
    """Make everything this kernel outputs shortcode-free; ``False`` outside IPython.

    Three doors: ``display()`` and every raw display (a Plotly figure shows
    itself that way) go through the display publisher's hooks; a cell's last
    value goes through the display formatter; ``print`` goes to the streams.
    Idempotent.
    """
    import sys

    try:
        from IPython import get_ipython
    except ImportError:  # pragma: no cover - no IPython, no outputs to guard
        return False
    shell = get_ipython()
    if shell is None:
        return False
    if getattr(shell, "_depictio_inert_outputs", False):
        return True

    def hook(msg: dict) -> dict:
        content = msg.get("content") or {}
        if "data" in content:
            content["data"] = defuse_output(content["data"])
        return msg

    publisher = getattr(shell, "display_pub", None)
    if hasattr(publisher, "register_hook"):
        publisher.register_hook(hook)

    formatter = shell.display_formatter
    original_format = formatter.format

    def format(obj: Any, include: Any = None, exclude: Any = None) -> Any:
        data, metadata = original_format(obj, include=include, exclude=exclude)
        return defuse_output(data), metadata

    formatter.format = format

    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        original_write = stream.write

        def write(text: Any, _write: Any = original_write) -> Any:
            return _write(_defuse_text(text) if isinstance(text, str) else text)

        try:
            stream.write = write
        except (AttributeError, TypeError):  # pragma: no cover - a read-only stream
            pass
    shell._depictio_inert_outputs = True
    return True
