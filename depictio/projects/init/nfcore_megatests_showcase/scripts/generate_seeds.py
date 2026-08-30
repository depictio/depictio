"""Generate the nfcore_megatests_showcase ``.db_seeds`` dashboards.

The dashboards are authored as lite YAML under ``../dashboards/``; this is a
thin entry point kept so the path documented in ``upload.sh`` and the README
keeps working. All the logic lives in the shared generator, which builds this
project's seeds and the advanced_viz_showcase ones the same way.

This script used to hold ~500 lines of hand-assembled JSON with the project,
workflow and DC ObjectIds transcribed into it. Those now come from
``../project.yaml``, so there is one copy of each id instead of two.

Usage (equivalent):
    python depictio/projects/init/nfcore_megatests_showcase/scripts/generate_seeds.py
    venv/bin/python -m depictio.dev_scripts.generate_dashboard_seeds nfcore_megatests_showcase
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[5]))

from depictio.dev_scripts.generate_dashboard_seeds import generate  # noqa: E402

if __name__ == "__main__":
    count = generate("nfcore_megatests_showcase")
    print(f"{count} dashboard(s) written")
