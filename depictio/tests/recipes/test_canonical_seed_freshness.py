"""Every committed ``*_canonical.tsv`` must match what its recipe produces today.

A reference project does not run its recipes. ``materialize_recipe_seeds``
turns each ``source: transformed`` DC into a file scan of the committed TSV, so
a recipe fix is invisible until someone regenerates that file — and nothing
made them. ``upset_canonical`` shipped for two years without the
``Kingdom``/``Phylum`` columns its own recipe had been fixed to add, which is
why a dashboard filter on a taxonomic rank silently did nothing.

The logic lives in ``depictio.dev_scripts.canonical_seed_freshness`` so the
test and the ``--write`` regeneration cannot disagree about what "current"
means. Seeds whose sources are not in the repo are reported as skips naming
the missing file, never as passes.
"""

from __future__ import annotations

import polars as pl
import pytest

from depictio.dev_scripts.canonical_seed_freshness import (
    PROJECTS,
    ProjectSeeds,
    compare,
    discover,
    produce,
)


def _cases() -> list[tuple[ProjectSeeds, object]]:
    return [(project, spec) for project in PROJECTS for spec in discover(project)[0]]


@pytest.mark.no_db
@pytest.mark.parametrize("project", PROJECTS, ids=lambda p: p.name)
def test_some_seed_is_checkable(project: ProjectSeeds):
    """A resolver that silently resolves nothing would make this file vacuous."""
    checkable, skipped = discover(project)
    assert checkable, f"no {project.name} seed could be checked (skipped: {skipped})"


@pytest.mark.no_db
@pytest.mark.parametrize(
    "project,spec", _cases(), ids=lambda x: getattr(x, "dc_tag", getattr(x, "name", ""))
)
def test_committed_seed_matches_its_recipe(project: ProjectSeeds, spec):
    produced = produce(spec)
    committed = pl.read_csv(spec.seed_path, separator="\t")
    message = compare(produced, committed)
    assert message is None, (
        f"{spec.seed_path.relative_to(project.data_root.parents[3])} is out of step with "
        f"{spec.recipe_path.name}: {message}. "
        "Regenerate with: venv/bin/python -m depictio.dev_scripts.canonical_seed_freshness --write"
    )
