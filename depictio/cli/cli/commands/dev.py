"""Hidden ``dev`` command group: maintainer / CI tooling.

These commands are not part of a day-to-day data → dashboard workflow — they
author and validate the bioinformatics catalog, run recipe transforms in
isolation, regenerate committed schema/index files, and audit backup coverage.
They are mounted under a single hidden ``dev`` group so they stay fully callable
(``depictio dev <group> <cmd>``) without cluttering the user-facing help.
"""

from __future__ import annotations

import typer

from depictio.cli.cli.commands.backup import dev_app as backup_dev
from depictio.cli.cli.commands.catalog import dev_app as catalog_dev
from depictio.cli.cli.commands.recipe import app as recipe

app = typer.Typer(help="Maintainer / CI tooling (not needed for day-to-day use).")

app.add_typer(recipe, name="recipe", help="Recipe authoring & standalone test harness")
app.add_typer(catalog_dev, name="catalog", help="Catalog validation, schema & index maintenance")
app.add_typer(backup_dev, name="backup", help="Backup validation-coverage audit")
