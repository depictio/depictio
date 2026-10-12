"""A runs regex guessed from the folders of the data root (config by example).

With the ``sequencing-runs`` structure every first-level folder whose name
matches ``runs_regex`` is a run. The names usually share one shape
(``run_12``, ``batch-07``, ``2020-01-05-a1``): the regex is read off that
shape instead of typed.

A name is cut at ``-``, ``_``, ``.`` and spaces. Names with the same
separators and the same digit-only segments form a group, and the largest
group wins; the other folders (a ``notes`` folder next to the runs) are
left out and reported. Inside the group a segment becomes

- a digit class (``\\d{4}``, ``\\d+`` when the lengths differ),
- the literal text when every name has it and it is letters (``run``),
- ``<letters>\\d+`` for ``set1``, ``set2`` (letters kept when shared),
- else the narrowest character class that holds every value (``[A-Z0-9]+``).
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from pathlib import PurePosixPath
from typing import Any

from depictio.cli.cli.utils.data_root import DataRoot
from depictio.models.local_access import is_hidden_name
from depictio.project_builder import tree
from depictio.project_builder.errors import BuilderRefused

_SEPARATORS = re.compile(r"([-_. ])")
_LETTERS_THEN_DIGITS = re.compile(r"([A-Za-z]+)(\d+)")
# How many left-out folders are named in the answer.
MAX_SKIPPED_SHOWN = 20
# What an overview reads: runs, files per run, depth, and what it names back.
MAX_RUNS_READ = 200
MAX_FILES_PER_RUN = 3000
MAX_DEPTH = 8
MAX_RUNS_SHOWN = 60
MAX_SHAPES = 40
MAX_DEVIATING = 20
MAX_DIFFS_SHOWN = 6


def _split(name: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """``(segments, separators)`` of a folder name."""
    parts = _SEPARATORS.split(name)
    return tuple(parts[0::2]), tuple(parts[1::2])


def _char_class(values: list[str]) -> str:
    chars = "".join(values)
    pieces = []
    if any(c.isupper() for c in chars):
        pieces.append("A-Z")
    if any(c.islower() for c in chars):
        pieces.append("a-z")
    if any(c.isdigit() for c in chars):
        pieces.append("0-9")
    others = sorted({c for c in chars if not c.isalnum()})
    pieces.extend(re.escape(c) for c in others)
    return f"[{''.join(pieces)}]+"


def _digits(values: list[str]) -> str:
    lengths = {len(v) for v in values}
    if len(lengths) != 1:
        return r"\d+"
    length = lengths.pop()
    return r"\d" if length == 1 else rf"\d{{{length}}}"


def _segment(values: list[str]) -> str:
    """The regex for one position of the name, over every value seen there."""
    if all(v.isdigit() for v in values):
        return _digits(values)
    unique = set(values)
    if len(unique) == 1 and values[0].isalpha():
        return re.escape(values[0])
    split = [_LETTERS_THEN_DIGITS.fullmatch(v) for v in values]
    if all(split):
        letters = {m.group(1) for m in split if m}
        head = (
            re.escape(letters.pop())
            if len(letters) == 1
            else _char_class([m.group(1) for m in split if m])
        )
        return head + _digits([m.group(2) for m in split if m])
    return _char_class(values)


def regex_for(names: list[str]) -> tuple[str | None, list[str]]:
    """``(regex, names it covers)`` for the biggest group of look-alike names.

    ``(None, [])`` when nothing repeats: several names that all differ in shape
    say nothing about what a run looks like.
    """
    groups: dict[tuple[Any, ...], list[str]] = {}
    for name in names:
        segments, separators = _split(name)
        key = (separators, tuple(s.isdigit() for s in segments))
        groups.setdefault(key, []).append(name)
    if not groups:
        return None, []
    # The biggest group; on a tie the first seen, which is the first by name.
    members = max(groups.values(), key=len)
    if len(members) < 2 and len(names) > 2:
        return None, []
    split = [_split(name) for name in members]
    separators = split[0][1]
    columns = list(zip(*(segments for segments, _ in split), strict=True))
    out = [_segment(list(column)) for column in columns]
    pattern = out[0]
    for sep, part in zip(separators, out[1:], strict=True):
        pattern += (r"\." if sep == "." else sep) + part
    regex = f"^{pattern}$"
    # A regex that misses its own examples is worse than none.
    covered = [name for name in members if re.match(regex, name)]
    return (regex, covered) if len(covered) == len(members) else (None, [])


def _first_level_folders(root: DataRoot) -> tuple[list[str], bool]:
    """``(visible first-level folder names, listing truncated)`` of ``root``."""
    listing = tree.list_folder(root, "")
    folders = sorted(
        entry["name"]
        for entry in listing["entries"]
        if entry["is_dir"] and not is_hidden_name(entry["name"])
    )
    return folders, bool(listing["truncated"])


def suggest_runs_regex(root: DataRoot) -> dict[str, Any]:
    """The runs regex for the first-level folders of ``root``, with the runs it
    matches and the folders it leaves out."""
    folders, truncated = _first_level_folders(root)
    regex, runs = regex_for(folders)
    matched = set(runs)
    skipped = [name for name in folders if name not in matched]
    return {
        "regex": regex,
        "runs": runs,
        "folders": len(folders),
        "skipped": skipped[:MAX_SKIPPED_SHOWN],
        "truncated": truncated,
    }


def _threshold(runs: int) -> int:
    """How many runs must hold a name for it to count as part of the layout."""
    return 1 if runs <= 1 else max(2, math.ceil(runs / 2))


def _wild(segment: str, last: bool) -> str:
    if not last:
        return "*"
    suffix = "".join(PurePosixPath(segment).suffixes)
    return f"*{suffix}" if suffix else "*"


def layout_shapes(per_run: dict[str, list[tuple[str, ...]]]) -> dict[str, set[str]]:
    """Each run's files as shapes: the path with the names that belong to one
    run only (a sample, a batch) replaced by ``*`` and the file's extension kept.

    A name is part of the layout when it sits under the same folder shape in at
    least half of the runs (and in two of them). Read depth by depth, so
    ``<sample>/counts/<sample>.tsv`` is ``*/counts/*.tsv`` whatever the samples
    are called.
    """
    threshold = _threshold(len(per_run))
    # (run, path parts, shape prefix so far)
    live = [(run, parts, ()) for run, files in per_run.items() for parts in files]
    shapes: dict[str, set[str]] = defaultdict(set)
    depth = 0
    while live:
        seen: dict[tuple[str, ...], dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        for run, parts, prefix in live:
            seen[prefix][parts[depth]].add(run)
        advanced = []
        for run, parts, prefix in live:
            last = depth == len(parts) - 1
            name = parts[depth]
            literal = len(seen[prefix][name]) >= threshold
            shape = (*prefix, name if literal else _wild(name, last))
            if last:
                shapes[run].add("/".join(shape))
            else:
                advanced.append((run, parts, shape))
        live = advanced
        depth += 1
    return shapes


def _runs_in_the_root(root: DataRoot, runs_regex: str | None) -> tuple[list[str], list[str], bool]:
    """``(runs, other folders, listing truncated)`` for a regex."""
    if not runs_regex or not runs_regex.strip():
        raise BuilderRefused(400, "Sequencing runs need a runs regex.", "runs_regex_missing")
    try:
        re.compile(runs_regex)
    except (re.error, OverflowError, RecursionError) as exc:
        raise BuilderRefused(400, f"Invalid runs regex: {exc}", "runs_regex_invalid") from exc
    folders, truncated = _first_level_folders(root)
    runs = root.runs(runs_regex)
    taken = set(runs)
    return runs, [name for name in folders if name not in taken], truncated


def overview(root: DataRoot, runs_regex: str | None) -> dict[str, Any]:
    """What a runs regex takes in: the runs, the layout their files share, and
    the runs that depart from it.

    The files of each run are walked by the scan's own walk (``root.match``),
    so what is shown is what a collection's scan can reach.
    """
    runs, others, truncated = _runs_in_the_root(root, runs_regex)
    read = runs[:MAX_RUNS_READ]
    truncated = truncated or len(runs) > len(read)
    per_run: dict[str, list[tuple[str, ...]]] = {}
    files_total = 0
    for run in read:
        files = root.match(".*", within=run, max_depth=MAX_DEPTH)
        parts = [
            rel_parts
            for rel in files
            if (rel_parts := PurePosixPath(rel).relative_to(run).parts)
            and not any(is_hidden_name(part) for part in rel_parts)
        ]
        if len(parts) > MAX_FILES_PER_RUN:
            parts = parts[:MAX_FILES_PER_RUN]
            truncated = True
        per_run[run] = parts
        files_total += len(parts)
    shapes = layout_shapes({run: files for run, files in per_run.items() if files})
    presence: Counter[str] = Counter()
    for found in shapes.values():
        presence.update(found)
    needed = _threshold(len(read))
    core = {shape for shape, count in presence.items() if count >= needed}
    deviating = []
    for run in read:
        found = shapes.get(run, set())
        missing = sorted(core - found)
        extra = sorted(found - core)
        if missing or extra:
            deviating.append(
                {
                    "run": run,
                    "files": len(per_run[run]),
                    "missing": missing[:MAX_DIFFS_SHOWN],
                    "extra": extra[:MAX_DIFFS_SHOWN],
                }
            )
    layout = sorted(presence.items(), key=lambda item: (-item[1], item[0]))[:MAX_SHAPES]
    return {
        "regex": runs_regex,
        "runs_total": len(runs),
        "runs": runs[:MAX_RUNS_SHOWN],
        "runs_read": len(read),
        "skipped": others[:MAX_SKIPPED_SHOWN],
        "files": files_total,
        "layout": [{"shape": shape, "runs": count} for shape, count in layout],
        "consistent": len(read) - len(deviating),
        "deviating": deviating[:MAX_DEVIATING],
        "deviating_total": len(deviating),
        "truncated": truncated,
    }
