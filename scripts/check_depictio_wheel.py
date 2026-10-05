"""Check the depictio wheel before it is tested or published.

The package-data globs in pyproject.toml keep the wheel to what `depictio local up`
reads. This fails if the wheel grows back or loses a file it needs.

    python3 scripts/check_depictio_wheel.py dist/depictio-*.whl
"""

import os
import re
import sys
import zipfile

MAX_MB = 15
REQUIRED = [
    r"depictio/viewer/dist/index\.html",
    r"depictio/projects/init/iris/\.db_seeds/dashboard\.json",
    r"depictio/projects/init/penguins/\.db_seeds/dashboard\.json",
    r"depictio/projects/nf-core/rnaseq/[^/]+/template\.yaml",
]
FORBIDDEN = [
    r"depictio/tests/",
    r"depictio/dev_scripts/",
    r"depictio/projects/nf-core/.*/docs/",
    # Thumbnails other than the iris and penguins dashboards.
    r"depictio/api/static/screenshots/(?!6824cb3b89d2b7216930973[78]_)",
]


def problems(path: str) -> list[str]:
    names = zipfile.ZipFile(path).namelist()
    size_mb = os.path.getsize(path) / 1e6
    print(f"{os.path.basename(path)}: {size_mb:.1f} MB, {len(names)} files")
    errors = [f"missing {p}" for p in REQUIRED if not any(re.fullmatch(p, n) for n in names)]
    errors += [f"forbidden {n}" for n in names if any(re.match(p, n) for p in FORBIDDEN)]
    if size_mb > MAX_MB:
        errors.append(f"wheel is {size_mb:.1f} MB, over the {MAX_MB} MB cap")
    return errors


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(f"usage: {sys.argv[0]} <depictio wheel>")
    sys.exit("\n".join(problems(sys.argv[1])[:20]) or None)
