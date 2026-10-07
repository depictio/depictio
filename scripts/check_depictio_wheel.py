"""Check the depictio wheel, and the depictio-cli alias wheel, before they are tested or published.

The package-data globs in pyproject.toml keep the wheel to what `depictio local up`
reads. This fails if the wheel grows back or loses a file it needs.

depictio-cli is an alias of depictio: it depends on the same version and ships a copy of
the files older depictio-cli releases installed, so that `pip install -U depictio-cli`
over one of them does not delete files depictio now owns. The copy has to be identical
to depictio's, or whichever package pip installs last would win.

    python3 scripts/check_depictio_wheel.py dist/depictio-*.whl [dist/depictio_cli-*.whl]
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
    r"depictio/cli/(build|venv)/",
    r"depictio/projects/nf-core/.*/docs/",
    # Thumbnails other than the iris and penguins dashboards.
    r"depictio/api/static/screenshots/(?!6824cb3b89d2b7216930973[78]_)",
]
CLI_SCRIPTS = {"depictio", "depictio-cli"}


def problems(path: str) -> list[str]:
    names = zipfile.ZipFile(path).namelist()
    size_mb = os.path.getsize(path) / 1e6
    print(f"{os.path.basename(path)}: {size_mb:.1f} MB, {len(names)} files")
    errors = [f"missing {p}" for p in REQUIRED if not any(re.fullmatch(p, n) for n in names)]
    errors += [f"forbidden {n}" for n in names if any(re.match(p, n) for p in FORBIDDEN)]
    if size_mb > MAX_MB:
        errors.append(f"wheel is {size_mb:.1f} MB, over the {MAX_MB} MB cap")
    return errors


def _dist_info(wheel: zipfile.ZipFile, name: str) -> str:
    path = next(n for n in wheel.namelist() if n.endswith(f".dist-info/{name}"))
    return wheel.read(path).decode()


def _normalize(version: str) -> str:
    """PEP 440 spelling of the pre-releases we tag: 1.12.0-b1 is 1.12.0b1."""
    return re.sub(r"[-_.]?(a|b|rc)[-_.]?(\d+)", r"\1\2", version.lower())


def _version(wheel: zipfile.ZipFile) -> str:
    return re.search(r"^Version: (.+)$", _dist_info(wheel, "METADATA"), re.M).group(1)


def _scripts(wheel: zipfile.ZipFile) -> set[str]:
    entry_points = _dist_info(wheel, "entry_points.txt")
    section = entry_points.split("[console_scripts]", 1)[-1].split("\n[", 1)[0]
    return {line.split("=")[0].strip() for line in section.splitlines() if "=" in line}


def alias_problems(depictio_path: str, alias_path: str) -> list[str]:
    depictio, alias = zipfile.ZipFile(depictio_path), zipfile.ZipFile(alias_path)
    print(f"{os.path.basename(alias_path)}: {len(alias.namelist())} files")
    version = _version(depictio)
    errors = []
    if _version(alias) != version:
        errors.append(f"depictio-cli is {_version(alias)}, depictio is {version}")
    requires = re.findall(r"^Requires-Dist: (.+)$", _dist_info(alias, "METADATA"), re.M)
    for name in ("depictio", "depictio[multiqc]"):
        pins = [r[len(name) + 2 :].split(";")[0] for r in requires if r.startswith(f"{name}==")]
        if [_normalize(pin.strip()) for pin in pins] != [version]:
            errors.append(f"depictio-cli does not require {name}=={version}: {requires}")
    if missing := CLI_SCRIPTS - _scripts(alias):
        errors.append(f"depictio-cli lacks the scripts {sorted(missing)}")
    owned = set(depictio.namelist())
    for name in alias.namelist():
        if ".dist-info/" in name:
            continue
        if name not in owned:
            errors.append(f"depictio-cli ships {name}, which depictio does not")
        elif alias.read(name) != depictio.read(name):
            errors.append(f"depictio-cli's copy of {name} differs from depictio's")
    return errors


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        sys.exit(f"usage: {sys.argv[0]} <depictio wheel> [<depictio-cli wheel>]")
    errors = problems(sys.argv[1])
    if len(sys.argv) == 3:
        errors += alias_problems(sys.argv[1], sys.argv[2])
    sys.exit("\n".join(errors[:20]) or None)
