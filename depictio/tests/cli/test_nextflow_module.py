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
NEXTFLOW = REPO_ROOT / "depictio" / "cli" / "configs" / "nextflow"
INGEST = NEXTFLOW / "modules" / "depictio" / "ingest"
PUBLISH = NEXTFLOW / "subworkflows" / "depictio" / "publish"


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

    def test_every_option_it_passes_is_a_cli_option(self):
        """A renamed or removed CLI option would only surface at the end of a pipeline."""
        root = typer.main.get_command(app)

        def options(command) -> set[str]:
            return {opt for param in command.params for opt in (*param.opts, *param.secondary_opts)}

        def flags(text: str) -> set[str]:
            return set(re.findall(r"(?<![\w-])--[a-z][a-z-]+", text))

        script = _main().split("script:", 1)[1].split("stub:", 1)[0]
        local_up = re.findall(r"depictio local up([^\n]*)", script)
        assert local_up, "the artifact no longer starts its stack"
        up_flags = flags("".join(local_up))
        assert up_flags <= options(root.commands["local"].commands["up"]), up_flags
        ingest_flags = flags(re.sub(r"depictio local (up|down)[^\n]*", "", script))
        assert ingest_flags and ingest_flags <= options(root.commands["ingest"]), (
            ingest_flags - options(root.commands["ingest"])
        )

    def test_the_artifact_stack_lives_in_the_work_directory(self):
        """Never ~/.depictio/local: the task's stack is its own, and so is its data."""
        assert 'export DEPICTIO_LOCAL_HOME="$PWD/stack"' in _main().replace("\\$", "$")

    def test_the_artifact_stack_is_stopped_on_every_exit(self):
        """A failed ingestion must not leave MongoDB, SeaweedFS or the API running."""
        main = _main()
        assert "trap 'depictio local down" in main
        assert re.search(r"^\s*depictio local down$", main, re.MULTILINE)

    def test_the_stack_takes_its_options_from_ext_args2(self):
        """The API port (--port) is set from a config, as nf-core does for a second command."""
        script = _main().split("script:", 1)[1].split("stub:", 1)[0]
        assert re.search(r"def args2 = task\.ext\.args2 \?: ''", script)
        assert re.search(r"depictio local up --no-open --examples none \$\{args2\}", script)

    def test_directories_are_staged_as_real_trees(self):
        """The scan skips symlinked directories, so linking one whole loses its files."""
        assert 'cp -rsfL "$src/." "$dst/"' in _main().replace("\\$", "$")

    def test_the_cli_is_called_as_depictio(self):
        main = _main()
        assert re.search(r"^\s*depictio \\\\$", main, re.MULTILINE)
        assert "depictio-cli " not in main.replace("depictio-cli:", "")


class TestPinsFollowThePackageVersion:
    def test_container_tag(self):
        """The all-in-one image: the CLI image has no server and no services, so the
        artifact's `depictio local up` could not start in it."""
        tags = re.findall(r'container "ghcr\.io/depictio/depictio-allinone:([^"]+)"', _main())
        assert tags == [_package_version()]
        assert "depictio-cli:" not in _main()

    def test_the_container_image_bakes_its_services_prefix(self):
        """`local up` in the task reads the services the image preinstalled: nothing
        is downloaded, and nothing is for the user to set."""
        dockerfile = (REPO_ROOT / "docker-images" / "allinone" / "Dockerfile").read_text()
        assert "DEPICTIO_SERVICES_PREFIX=/opt/depictio-services" in dockerfile
        assert "install_services.py local_stack.py /opt/depictio-services" in dockerfile

    def test_a_container_uid_without_a_writable_home_gets_one(self):
        """`docker -u $(id -u)` leaves HOME=/ for a uid the image does not know."""
        assert 'export HOME="\\$PWD/.home"' in _main()

    def test_conda_pin(self):
        env = (INGEST / "environment.yml").read_text()
        assert re.findall(r"depictio\[local\]==(\S+)", env) == [_package_version()]

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
        """The image's ENTRYPOINT (tini + the all-in-one entrypoint) is not needed to
        run the task's bash; cleared so nothing stands between Nextflow and bash."""
        assert (
            "containerOptions \"${workflow.containerEngine in ['docker', 'podman'] "
            "? '--entrypoint \"\"' : ''}\""
        ) in _main()


class TestPublishSubworkflow:
    """depictio/publish: the module for any pipeline, settings from params.depictio_*."""

    def test_it_ships_the_nf_core_subworkflow_files(self):
        for name in ("main.nf", "meta.yml", "nextflow.config", "tests/main.nf.test"):
            assert (PUBLISH / name).is_file(), name

    def test_it_includes_the_module_it_ships_with(self):
        main = (PUBLISH / "main.nf").read_text()
        include = re.search(r"include \{ DEPICTIO_INGEST \} from '([^']+)'", main).group(1)
        assert (PUBLISH / include).with_suffix(".nf").resolve() == (INGEST / "main.nf").resolve()

    def test_it_reads_no_params(self):
        """nf-core asks a subworkflow to take every setting as an input."""
        code = [line.split("//", 1)[0] for line in (PUBLISH / "main.nf").read_text().splitlines()]
        assert not [line for line in code if "params." in line]

    def test_its_selector_matches_with_or_without_an_enclosing_workflow(self):
        selector = re.search(
            r"withName: '([^']+)'", (PUBLISH / "nextflow.config").read_text()
        ).group(1)
        for name in (
            "DEPICTIO_PUBLISH:DEPICTIO_INGEST",
            "NFCORE_RNASEQ:DEPICTIO_PUBLISH:DEPICTIO_INGEST",
        ):
            assert re.fullmatch(selector, name), name

    def test_meta_yml_documents_its_takes_and_emits(self):
        meta = yaml.safe_load((PUBLISH / "meta.yml").read_text())
        main = (PUBLISH / "main.nf").read_text()
        take = main.split("take:", 1)[1].split("main:", 1)[0]
        emit = main.split("emit:", 1)[1]
        assert [next(iter(i)) for i in meta["input"]] == re.findall(r"^\s+(\w+)\s+//", take, re.M)
        assert [next(iter(o)) for o in meta["output"]] == re.findall(r"^\s+(\w+)\s+=", emit, re.M)
