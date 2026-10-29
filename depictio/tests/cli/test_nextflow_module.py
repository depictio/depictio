"""The `depictio/ingest` Nextflow module shipped under cli/configs/nextflow/modules.

A pipeline vendors the directory as is, so nothing here runs Nextflow: these
tests guard what a pipeline would only find out at run time. That is the module
layout nf-core tooling expects, a declared interface that matches the process,
and a container and conda pin that follow the package version, since a pin left
behind would ingest with the previous release's templates.
"""

from __future__ import annotations

import configparser
import re
import tomllib
from pathlib import Path

import typer
import yaml

from depictio.cli.depictio_cli import app

REPO_ROOT = Path(__file__).resolve().parents[3]
INGEST = REPO_ROOT / "depictio" / "cli" / "configs" / "nextflow" / "modules" / "depictio" / "ingest"


def _package_version() -> str:
    return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())["project"]["version"]


def _main() -> str:
    return (INGEST / "main.nf").read_text()


def _input_block() -> str:
    return _main().split("input:", 1)[1].split("output:", 1)[0]


def _declared_inputs() -> list[str]:
    """Input names in declaration order, comments stripped."""
    names: list[str] = []
    for line in _input_block().splitlines():
        line = line.split("//", 1)[0].strip()
        if not line:
            continue
        if line.startswith("tuple"):
            names += re.findall(r"(?:val|path)\((\w+)", line)
        else:
            names.append(re.match(r"(?:val|path)\s+(\w+)", line).group(1))
    return names


class TestLayout:
    def test_it_ships_the_nf_core_module_files(self):
        for name in ("main.nf", "meta.yml", "environment.yml", "tests/main.nf.test"):
            assert (INGEST / name).is_file(), name

    def test_the_process_is_named_after_the_module_path(self):
        """nf-core derives DEPICTIO_INGEST from depictio/ingest."""
        assert re.search(r"^process DEPICTIO_INGEST \{", _main(), re.MULTILINE)


class TestInterface:
    def test_meta_yml_documents_every_input_in_order(self):
        meta = yaml.safe_load((INGEST / "meta.yml").read_text())
        documented: list[str] = []
        for channel in meta["input"]:
            items = channel if isinstance(channel, list) else [channel]
            documented += [next(iter(item)) for item in items]
        assert documented == _declared_inputs()

    def test_meta_yml_documents_every_emitted_channel(self):
        meta = yaml.safe_load((INGEST / "meta.yml").read_text())
        emitted = re.findall(r"emit:\s*(\w+)", _main())
        assert list(meta["output"]) == emitted

    def test_every_option_it_passes_is_an_ingest_option(self):
        """A renamed or removed CLI option would only surface at the end of a pipeline."""
        command = typer.main.get_command(app).commands["ingest"]
        known = {opt for param in command.params for opt in param.opts}
        script = _main().split("script:", 1)[1].split("stub:", 1)[0]
        passed = set(re.findall(r"(?<![\w-])--[a-z][a-z-]+", script))
        assert passed and passed <= known, passed - known

    def test_directories_are_staged_as_real_trees(self):
        """The scan skips symlinked directories, so linking one whole loses its files."""
        assert 'cp -rsfL "$src/." "$dst/"' in _main().replace("\\$", "$")

    def test_the_cli_is_called_as_depictio(self):
        main = _main()
        assert re.search(r"^\s*depictio \\\\$", main, re.MULTILINE)
        assert "depictio-cli " not in main.replace("depictio-cli:", "")


class TestPinsFollowThePackageVersion:
    def test_container_tag(self):
        tags = re.findall(r'container "ghcr\.io/depictio/depictio-cli:([^"]+)"', _main())
        assert tags == [_package_version()]

    def test_conda_pin(self):
        env = (INGEST / "environment.yml").read_text()
        assert re.findall(r"depictio\[multiqc\]==(\S+)", env) == [_package_version()]

    def test_bumpversion_rewrites_both_pins(self):
        cfg = configparser.ConfigParser(interpolation=None)
        cfg.read(REPO_ROOT / ".bumpversion.cfg")
        version = cfg["bumpversion"]["current_version"]
        rel = INGEST.relative_to(REPO_ROOT).as_posix()
        for name in ("main.nf", "environment.yml"):
            section = cfg[f"bumpversion:file:{rel}/{name}"]
            search = section["search"].replace("{current_version}", version)
            assert (INGEST / name).read_text().count(search) == 1, name

    def test_the_image_entrypoint_is_cleared_for_docker_and_podman(self):
        """The CLI image's ENTRYPOINT would otherwise receive bash as a subcommand."""
        assert (
            "containerOptions \"${workflow.containerEngine in ['docker', 'podman'] "
            "? '--entrypoint \"\"' : ''}\""
        ) in _main()
