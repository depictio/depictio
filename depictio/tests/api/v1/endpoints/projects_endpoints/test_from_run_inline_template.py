"""``POST /projects/from_run`` with an inline template (``FromRunRequest.template``).

The Project Builder assembles an ad-hoc ``custom/<name>`` template in the
browser and hands it to ``from_run`` in place of a template id. It is held to
``validate_inline_template`` first (the browser is not the operator), resolved
from memory against the run folder with the very ``resolve_template_config`` a
template file goes through, confined to the data root like any resolved
config, previewed and, unless it is a dry run, created: no template lookup, no
detection, no dashboards.

No network and no MongoDB: S3 is the shared CLI stub, the project collection is
mongomock, and the Celery dispatch is replaced at ``_dispatch_refresh_tasks``.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.datacollections_endpoints import utils as dc_utils
from depictio.api.v1.endpoints.projects_endpoints import (
    from_run,
    manifest_ingest,
    routes,
    storage_config,
)
from depictio.api.v1.endpoints.projects_endpoints.local_dirs import CodedHTTPException
from depictio.cli.cli.utils import run_detection
from depictio.cli.cli.utils import templates as templates_module
from depictio.models.models.users import UserBase
from depictio.models.s3_access import S3AccessRefused, S3Target
from depictio.project_builder.assemble import (
    DcDraft,
    ImageProps,
    MultiQCProps,
    ProjectDraft,
    TableProps,
    WorkflowDraft,
    build_template,
)
from depictio.project_builder.plan import plan_inline
from depictio.tests.cli.project_builder._fixtures import RUN_TREE, table_dc
from depictio.tests.cli.s3_stubs import (
    MEGATEST_TREE,
    S3_BUCKET,
    S3_KEY_PREFIX,
    S3_ROOT,
    data_root_for,
    install_s3_listing,
    s3_cli_config,
    write_tree,
)

TEMPLATE_ID = "nf-core/ampliseq/2.16.0"


def _user(is_admin: bool = False) -> UserBase:
    return UserBase(id=ObjectId(), email="owner@example.com", is_admin=is_admin)


def _request(host: str | None = "localhost:8058") -> Request:
    headers = [(b"host", host.encode())] if host is not None else []
    return Request({"type": "http", "method": "POST", "path": "/", "headers": headers})


def _call(
    data_root: str = S3_ROOT,
    template: dict | None = None,
    template_id: str | None = None,
    user=None,
    project_name: str | None = None,
    variables: dict[str, str] | None = None,
    dry_run: bool = False,
    request=None,
):
    return from_run._create_project_from_run(
        data_root=data_root,
        template_id=template_id,
        template=template,
        current_user=user or _user(),
        project_name=project_name,
        variables=variables,
        dry_run=dry_run,
        request=request,
    )


def _template(*collections: DcDraft, name: str = "Lab Run", **workflow) -> dict:
    draft = ProjectDraft(
        name=name,
        workflows=[WorkflowDraft(name="main", data_collections=list(collections), **workflow)],
    )
    return build_template(draft)


def _recursive(tag: str, regex: str, **fields) -> DcDraft:
    return DcDraft(
        tag=tag,
        type="table",
        mode="recursive",
        regex=regex,
        props=TableProps(format="csv", separator=","),
        **fields,
    )


def _megatest_template(**kwargs) -> dict:
    """Three collections over the megatest prefix: a file, a scan and a MultiQC report."""
    return _template(
        table_dc("sheet", path="input/samplesheet.csv"),
        _recursive("levels", r"^qiime2/barplot/level-\d\.csv$"),
        DcDraft(
            tag="mqc",
            type="multiqc",
            mode="single",
            path="multiqc/multiqc_data/multiqc.parquet",
            props=MultiQCProps(),
        ),
        **kwargs,
    )


def _local_template(**kwargs) -> dict:
    """The same over ``RUN_TREE``: a file, a scan and an optional file that is not there."""
    return _template(
        table_dc("sheet", path="samplesheet.csv"),
        DcDraft(
            tag="quant",
            type="table",
            mode="recursive",
            regex=r"^quant\.tsv$",
            props=TableProps(format="tsv", separator="\t"),
        ),
        table_dc("extra", path="not/there.csv", optional=True),
        **kwargs,
    )


def _rows(report) -> dict[str, object]:
    return {row.data_collection_tag: row for row in report.data_collections}


@pytest.fixture(autouse=True)
def server_context(monkeypatch):
    monkeypatch.setenv("DEPICTIO_CONTEXT", "server")
    monkeypatch.delenv("DEPICTIO_LOCAL_DATA_ROOTS", raising=False)
    monkeypatch.delenv("DEPICTIO_AUTH_SINGLE_USER_MODE", raising=False)
    monkeypatch.delenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", raising=False)
    monkeypatch.delenv("DEPICTIO_REMOTE_CREDENTIALED_S3_BUCKETS", raising=False)


@pytest.fixture()
def megatest_s3(monkeypatch):
    """The megatest prefix served by the stub, its bucket on the administrator's list."""
    monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", S3_BUCKET)
    return install_s3_listing(monkeypatch, MEGATEST_TREE, key_prefix=S3_KEY_PREFIX)


@pytest.fixture()
def no_client(monkeypatch):
    monkeypatch.setattr(S3Target, "client", lambda _target: pytest.fail("an S3 client was built"))


@pytest.fixture()
def local_home(tmp_path, monkeypatch):
    """Local folders on, ``home/`` the one root, the run at ``home/run42``."""
    home = tmp_path / "home"
    write_tree(home / "run42", RUN_TREE)
    (home / "depictio-local").mkdir()
    monkeypatch.setenv("DEPICTIO_AUTH_SINGLE_USER_MODE", "true")
    monkeypatch.setenv("DEPICTIO_LOCAL_DATA_ROOTS", str(home))
    monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(home / "depictio-local"))
    return home


@pytest.fixture()
def mock_db(monkeypatch):
    database = mongomock.MongoClient()["depictio_test"]
    with (
        patch.object(from_run, "projects_collection", database["projects"]),
        patch.object(routes, "projects_collection", database["projects"]),
        patch.object(manifest_ingest, "projects_collection", database["projects"]),
        patch.object(dc_utils, "projects_collection", database["projects"]),
        patch.object(dc_utils, "tokens_collection", database["tokens"]),
        patch.object(storage_config, "project_storage_collection", database["project_storage"]),
    ):
        yield database


@pytest.fixture()
def forbidden_paths(monkeypatch):
    """Fail the test if the catalogue, the detection or the dashboard import is touched."""
    monkeypatch.setattr(
        templates_module, "locate_template", lambda *a, **k: pytest.fail("locate_template")
    )
    monkeypatch.setattr(
        templates_module, "resolve_template", lambda *a, **k: pytest.fail("resolve_template")
    )
    monkeypatch.setattr(
        run_detection,
        "detect_template_for_root",
        lambda *a, **k: pytest.fail("template detection"),
    )
    monkeypatch.setattr(
        from_run, "_import_template_dashboards", lambda *a, **k: pytest.fail("dashboard import")
    )


# ── the request ──────────────────────────────────────────────────────────────


class TestRequestModel:
    def test_a_request_carries_an_inline_template_in_place_of_an_id(self):
        template = _megatest_template()
        request = from_run.FromRunRequest(data_root=S3_ROOT, template=template)
        assert request.template == template and request.template_id is None

    def test_neither_is_fine_the_template_is_then_detected(self):
        request = from_run.FromRunRequest(data_root=S3_ROOT)
        assert request.template is None and request.template_id is None

    def test_both_are_refused(self):
        with pytest.raises(ValidationError, match="Give template_id or template, not both."):
            from_run.FromRunRequest(
                data_root=S3_ROOT, template_id=TEMPLATE_ID, template=_megatest_template()
            )

    def test_an_empty_template_still_counts_as_one(self):
        with pytest.raises(ValidationError, match="not both"):
            from_run.FromRunRequest(data_root=S3_ROOT, template_id=TEMPLATE_ID, template={})
        assert from_run.FromRunRequest(data_root=S3_ROOT, template={}).template == {}

    def test_a_template_is_a_mapping(self):
        with pytest.raises(ValidationError):
            from_run.FromRunRequest(data_root=S3_ROOT, template=["not", "a", "mapping"])

    def test_the_template_id_rules_still_apply_next_to_it(self):
        with pytest.raises(ValidationError, match="slash-separated"):
            from_run.FromRunRequest(data_root=S3_ROOT, template_id="../x")

    @pytest.mark.asyncio
    async def test_the_route_hands_the_template_on(self):
        template = _megatest_template()
        payload = from_run.FromRunRequest(data_root=S3_ROOT, template=template, dry_run=True)
        with patch.object(routes, "_create_project_from_run", return_value={"ok": 1}) as work:
            await routes.create_project_from_run(payload, _request(), current_user=_user())
        assert work.call_args.kwargs["template"] == template
        assert work.call_args.kwargs["template_id"] is None

    @pytest.mark.asyncio
    async def test_the_route_answers_an_invalid_template_with_detail_and_code(self, megatest_s3):
        template = _megatest_template()
        template["dashboards"] = ["evil.yaml"]
        payload = from_run.FromRunRequest(data_root=S3_ROOT, template=template, dry_run=True)
        response = await routes.create_project_from_run(payload, _request(), current_user=_user())
        assert response.status_code == 422
        assert json.loads(response.body) == {
            "detail": "Unexpected top-level keys: dashboards.",
            "code": "inline_template_invalid",
        }


# ── a dry run ────────────────────────────────────────────────────────────────


class TestDryRunOnALocalFolder:
    def test_the_plan_is_the_from_run_report(self, local_home, mock_db, forbidden_paths):
        report = _call(
            data_root=str(local_home / "run42"),
            template=_local_template(),
            dry_run=True,
            request=_request(),
            user=_user(is_admin=True),
        )
        real = str((local_home / "run42").resolve())
        assert report.success is True and report.dry_run is True
        assert report.template_id == "custom/lab-run"
        assert report.project_name == "Lab Run"
        assert report.data_root == real
        assert report.project_id is None and report.run_id is None
        # No detection, no dashboards, no variables read from files.
        assert report.detected_template is None
        assert report.dashboards == [] and report.input_files == []
        assert mock_db["projects"].count_documents({}) == 0

        rows = _rows(report)
        assert (rows["sheet"].mode, rows["sheet"].status, rows["sheet"].matched) == (
            "single",
            "ok",
            1,
        )
        # A local root keeps the recursive scan: only a prefix turns it into s3_prefix.
        assert (rows["quant"].mode, rows["quant"].status, rows["quant"].matched) == (
            "recursive",
            "ok",
            3,
        )
        assert rows["quant"].samples[0] == f"{real}/star/S1/quant.tsv"
        assert (rows["extra"].status, rows["extra"].optional) == ("pruned", True)
        assert report.pruned_optional_dcs == ["extra"]

    def test_the_project_name_can_be_chosen(self, local_home, mock_db):
        report = _call(
            data_root=str(local_home / "run42"),
            template=_local_template(),
            project_name="Chosen name",
            dry_run=True,
            request=_request(),
            user=_user(is_admin=True),
        )
        assert report.project_name == "Chosen name"
        assert report.template_id == "custom/lab-run"

    def test_the_local_gates_are_the_same_as_for_a_catalogue_template(self, local_home, mock_db):
        for kwargs, code in (
            ({"request": _request("evil.example:8058")}, "non_loopback_host"),
            ({"request": None}, "non_loopback_host"),
            ({"request": _request(), "user": _user(is_admin=False)}, "local_admin_only"),
        ):
            with pytest.raises(CodedHTTPException) as exc:
                _call(
                    data_root=str(local_home / "run42"),
                    template=_local_template(),
                    dry_run=True,
                    **{"user": _user(is_admin=True), **kwargs},
                )
            assert (exc.value.status_code, exc.value.code) == (403, code)

    def test_a_folder_outside_the_allowed_roots_is_refused_before_the_template_is_read(
        self, local_home, tmp_path
    ):
        write_tree(tmp_path / "elsewhere", RUN_TREE)
        with patch("depictio.project_builder.validate.validate_inline_template") as validate:
            with pytest.raises(CodedHTTPException) as exc:
                _call(
                    data_root=str(tmp_path / "elsewhere"),
                    template=_local_template(),
                    dry_run=True,
                    request=_request(),
                    user=_user(is_admin=True),
                )
        assert exc.value.code == "local_path_outside"
        validate.assert_not_called()

    def test_a_local_folder_with_local_folders_off_is_refused(self, tmp_path):
        write_tree(tmp_path / "run42", RUN_TREE)
        with pytest.raises(CodedHTTPException) as exc:
            _call(
                data_root=str(tmp_path / "run42"),
                template=_local_template(),
                dry_run=True,
                request=_request(),
                user=_user(is_admin=True),
            )
        assert exc.value.code == "local_folders_off"

    def test_bounds_narrow_a_local_scan(self, local_home):
        template = _template(
            DcDraft(
                tag="quant",
                type="table",
                mode="recursive",
                regex=r"^quant\.tsv$",
                max_depth=1,
                props=TableProps(format="tsv", separator="\t"),
            )
        )
        report = _call(
            data_root=str(local_home / "run42"),
            template=template,
            dry_run=True,
            request=_request(),
            user=_user(is_admin=True),
        )
        # quant.tsv sits two folders down.
        assert _rows(report)["quant"].matched == 0
        assert _rows(report)["quant"].status == "empty"


class TestDryRunOnAnS3Prefix:
    def test_the_prefix_is_planned_through_its_one_listing(self, megatest_s3, mock_db):
        report = _call(template=_megatest_template(), dry_run=True)
        assert report.success is True and report.dry_run is True
        assert report.template_id == "custom/lab-run"
        assert report.data_root == S3_ROOT
        rows = _rows(report)
        assert (rows["sheet"].mode, rows["sheet"].status) == ("url", "ok")
        assert rows["sheet"].location == f"{S3_ROOT}/input/samplesheet.csv"
        assert (rows["levels"].mode, rows["levels"].status, rows["levels"].matched) == (
            "s3_prefix",
            "ok",
            1,
        )
        assert (rows["mqc"].mode, rows["mqc"].status, rows["mqc"].matched) == (
            "s3_prefix",
            "ok",
            1,
        )
        assert len(megatest_s3.listings) == 1
        assert mock_db["projects"].count_documents({}) == 0

    def test_the_run_folders_own_records_are_still_read(self, megatest_s3):
        report = _call(template=_megatest_template(), dry_run=True)
        assert report.run_info is not None and report.run_info.engine == "nextflow"

    def test_only_the_variables_the_template_declares_are_reported(self, megatest_s3):
        """The megatest folder's own parameters decide GROUP_COL and friends for a
        catalogue template; an inline template declares none of them."""
        report = _call(template=_megatest_template(), dry_run=True)
        assert report.resolved_variables == {}

    def test_the_catalogue_is_never_consulted(self, megatest_s3, forbidden_paths):
        _call(template=_megatest_template(), dry_run=True)

    def test_a_bucket_the_administrator_did_not_list_is_refused_from_configuration_alone(
        self, monkeypatch, no_client
    ):
        monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", "another-bucket")
        with pytest.raises(S3AccessRefused) as exc:
            _call(data_root="s3://private-bucket/run1", template=_megatest_template(), dry_run=True)
        assert (exc.value.status_code, exc.value.code) == (422, "s3_refused")

    def test_a_collection_that_finds_nothing_is_reported_not_refused(self, megatest_s3):
        template = _template(table_dc("sheet", path="input/nope.csv"), _recursive("x", r"^zzz$"))
        rows = _rows(_call(template=template, dry_run=True))
        assert (rows["sheet"].status, rows["x"].status) == ("missing", "empty")

    def test_the_plan_has_the_shape_the_standalone_plan_does(self, megatest_s3):
        template = _megatest_template()
        report = _call(template=template, dry_run=True)
        root = data_root_for(S3_ROOT, s3_cli_config())
        planned = plan_inline(template, root)
        assert set(planned) == set(from_run.FromRunReport.model_fields)
        validated = from_run.FromRunReport.model_validate(planned)
        assert validated.template_id == report.template_id
        assert [r.model_dump() for r in validated.data_collections] == [
            r.model_dump() for r in report.data_collections
        ]
        assert validated.resolved_variables == report.resolved_variables


# ── what is refused ──────────────────────────────────────────────────────────


class TestRefusals:
    def test_a_template_and_a_template_id_together_are_a_422(self, no_client):
        with pytest.raises(HTTPException) as exc:
            _call(template=_megatest_template(), template_id=TEMPLATE_ID, dry_run=True)
        assert exc.value.status_code == 422
        assert exc.value.detail == "Give template_id or template, not both."

    @pytest.mark.parametrize(
        ("change", "fragment"),
        [
            (lambda t: t.update(dashboards=["x.yaml"]), "Unexpected top-level keys: dashboards"),
            (
                lambda t: t["template"].update(conditional=[{"if": 1}]),
                "no dashboards, conditionals",
            ),
            (
                lambda t: t["template"].update(template_id="nf-core/rnaseq/1"),
                "template_id must look",
            ),
            (lambda t: t["workflows"].append(t["workflows"][0]), "Two workflows are named"),
            (lambda t: t["workflows"][0]["data_collections"][0].update(extra=1), "unexpected data"),
            (lambda t: t.pop("workflows"), "at least one workflow"),
        ],
    )
    def test_a_template_the_builder_could_not_have_produced_is_a_coded_422(
        self, megatest_s3, change, fragment
    ):
        template = _megatest_template()
        change(template)
        with pytest.raises(CodedHTTPException) as exc:
            _call(template=template, dry_run=True)
        assert (exc.value.status_code, exc.value.code) == (422, "inline_template_invalid")
        assert fragment in exc.value.detail

    def test_an_empty_mapping_is_a_template_without_its_section_not_no_template(
        self, megatest_s3, forbidden_paths
    ):
        """`{}` is falsy, but it is a template: it is refused, not replaced by detection."""
        with pytest.raises(CodedHTTPException) as exc:
            _call(template={}, dry_run=True)
        assert exc.value.code == "inline_template_invalid"
        assert exc.value.detail == "The template section is missing."

    def test_a_filename_climbing_out_of_the_root_is_refused(self, megatest_s3):
        template = _megatest_template()
        template["workflows"][0]["data_collections"][0]["config"]["scan"]["scan_parameters"][
            "filename"
        ] = "{DATA_ROOT}/../x"
        with pytest.raises(CodedHTTPException) as exc:
            _call(template=template, dry_run=True)
        assert (exc.value.status_code, exc.value.code) == (422, "inline_template_invalid")
        assert "may not contain '..'" in exc.value.detail

    @pytest.mark.parametrize("filename", ["/etc/passwd", "s3://another-bucket/secret.csv"])
    def test_a_filename_outside_the_placeholder_is_refused(self, megatest_s3, filename):
        template = _megatest_template()
        template["workflows"][0]["data_collections"][0]["config"]["scan"]["scan_parameters"][
            "filename"
        ] = filename
        with pytest.raises(CodedHTTPException) as exc:
            _call(template=template, dry_run=True)
        assert exc.value.code == "inline_template_invalid"
        assert "must be a path under {DATA_ROOT}" in exc.value.detail

    def test_confinement_to_the_root_holds_even_if_validation_let_a_path_through(
        self, megatest_s3, mock_db
    ):
        """Defence in depth: the resolved config is checked against the root as for any template."""
        template = _megatest_template()
        template["workflows"][0]["data_collections"][0]["config"]["scan"]["scan_parameters"][
            "filename"
        ] = "/app/depictio/keys/private_key.pem"
        with (
            patch("depictio.project_builder.validate.validate_inline_template", return_value=[]),
            pytest.raises(HTTPException) as exc,
        ):
            _call(template=template)
        assert exc.value.status_code == 422
        assert "/app/depictio/keys/private_key.pem" in exc.value.detail
        assert "is not under the data root" in exc.value.detail
        assert mock_db["projects"].count_documents({}) == 0

    def test_a_local_filename_climbing_out_is_refused_by_confinement_too(self, local_home, mock_db):
        template = _local_template()
        template["workflows"][0]["data_collections"][0]["config"]["scan"]["scan_parameters"][
            "filename"
        ] = "{DATA_ROOT}/../outside.csv"
        with (
            patch("depictio.project_builder.validate.validate_inline_template", return_value=[]),
            pytest.raises(HTTPException) as exc,
        ):
            _call(
                data_root=str(local_home / "run42"),
                template=template,
                request=_request(),
                user=_user(is_admin=True),
            )
        assert exc.value.status_code == 422
        assert mock_db["projects"].count_documents({}) == 0

    def test_indexed_files_and_images_cannot_be_built_over_a_prefix(self, megatest_s3):
        template = _template(
            DcDraft(
                tag="imgs",
                type="image",
                mode="single",
                path="input/samplesheet.csv",
                props=ImageProps(image_column="img", local_images_path="images"),
            )
        )
        with pytest.raises(CodedHTTPException) as exc:
            _call(template=template, dry_run=True)
        assert exc.value.code == "inline_template_invalid"
        assert "Images are uploaded from a folder on this computer" in exc.value.detail

    def test_a_project_the_model_refuses_is_a_coded_422_before_anything_is_stored(
        self, megatest_s3, mock_db
    ):
        template = _megatest_template()
        template["project_type"] = "bogus"
        with pytest.raises(CodedHTTPException) as exc:
            _call(template=template)
        assert (exc.value.status_code, exc.value.code) == (422, "inline_template_invalid")
        assert exc.value.detail.startswith("project_type:")
        assert mock_db["projects"].count_documents({}) == 0

    def test_a_variable_outside_the_root_is_still_refused(self, megatest_s3):
        with pytest.raises(HTTPException) as exc:
            _call(template=_megatest_template(), variables={"X": "/etc/hostname"}, dry_run=True)
        assert exc.value.status_code == 422
        assert "Variable 'X' points outside the data root" in exc.value.detail

    def test_an_invalid_template_id_is_still_checked_without_a_template(self):
        with pytest.raises(HTTPException) as exc:
            _call(template_id="../../etc/passwd", dry_run=True)
        assert exc.value.status_code == 422


# ── creation ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def dispatch():
    """The Celery fan-out, replaced: one run opened, every collection dispatched."""
    with patch.object(
        from_run, "_dispatch_refresh_tasks", return_value=("run-1", True, [])
    ) as patched:
        yield patched


def _create(local_home, template=None, *, user=None, project_name=None):
    return _call(
        data_root=str(local_home / "run42"),
        template=template or _local_template(),
        user=user or _user(is_admin=True),
        project_name=project_name,
        request=_request(),
    )


class TestCreation:
    def test_the_project_is_created_from_the_template_as_if_it_were_a_catalogue_one(
        self, local_home, mock_db, dispatch, forbidden_paths
    ):
        user = _user(is_admin=True)
        report = _create(local_home, user=user)

        real = str((local_home / "run42").resolve())
        assert report.success is True and report.dry_run is False
        assert report.template_id == "custom/lab-run"
        assert report.project_id is not None and report.run_id == "run-1"
        assert report.dashboards == []
        assert report.storage_saved is False

        stored = mock_db["projects"].find_one({"_id": ObjectId(report.project_id)})
        assert stored["name"] == "Lab Run"
        assert stored["permissions"]["owners"][0]["_id"] == user.id
        origin = stored["template_origin"]
        assert origin["template_id"] == "custom/lab-run"
        assert origin["template_version"] == "1"
        assert origin["data_root"] == real
        tags = [
            dc["data_collection_tag"] for wf in stored["workflows"] for dc in wf["data_collections"]
        ]
        # The optional collection with no file was pruned before creation.
        assert tags == ["sheet", "quant"]
        assert report.pruned_optional_dcs == ["extra"]

    def test_the_ingestion_is_dispatched_for_each_collection_the_project_holds(
        self, local_home, mock_db, dispatch
    ):
        user = _user(is_admin=True)
        report = _create(local_home, user=user)

        dispatch.assert_called_once()
        kwargs = dispatch.call_args.kwargs
        assert kwargs["command"] == "from_run"
        assert kwargs["data_root"] == str((local_home / "run42").resolve())
        assert kwargs["current_user"] is user
        assert [(tag, matched) for tag, _id, _wf, matched in kwargs["to_dispatch"]] == [
            ("sheet", 1),
            ("quant", 3),
        ]
        assert kwargs["preflight_failed"] == [] and kwargs["preflight_skipped"] == []
        assert kwargs["scan_modes"] == {"sheet": "single", "quant": "recursive"}
        assert kwargs["project_dict"]["_id"] == ObjectId(report.project_id)

    def test_a_collection_whose_file_is_absent_is_failed_not_dispatched(
        self, local_home, mock_db, dispatch
    ):
        template = _template(
            table_dc("sheet", path="samplesheet.csv"), table_dc("absent", path="nope.csv")
        )
        _create(local_home, template)
        kwargs = dispatch.call_args.kwargs
        assert [t[0] for t in kwargs["to_dispatch"]] == ["sheet"]
        assert [t[0] for t in kwargs["preflight_failed"]] == ["absent"]

    def test_a_dispatch_that_did_not_complete_is_not_a_success(self, local_home, mock_db, dispatch):
        dispatch.return_value = ("run-2", False, [])
        report = _create(local_home)
        assert report.run_id == "run-2" and report.success is False
        assert report.project_id is not None

    def test_the_project_name_can_be_chosen(self, local_home, mock_db, dispatch):
        report = _create(local_home, project_name="Chosen name")
        stored = mock_db["projects"].find_one({"_id": ObjectId(report.project_id)})
        assert stored["name"] == "Chosen name"
        assert stored["template_origin"]["template_id"] == "custom/lab-run"

    def test_a_taken_name_is_a_409_as_on_create(self, local_home, mock_db, dispatch):
        user = _user(is_admin=True)
        _create(local_home, user=user)
        with pytest.raises(HTTPException) as exc:
            _create(local_home, user=user)
        assert exc.value.status_code == 409
        assert exc.value.detail == routes._project_taken("name")["message"]
        assert mock_db["projects"].count_documents({}) == 1
        assert dispatch.call_count == 1

    def test_a_dry_run_creates_nothing_and_dispatches_nothing(self, local_home, mock_db, dispatch):
        _call(
            data_root=str(local_home / "run42"),
            template=_local_template(),
            dry_run=True,
            request=_request(),
            user=_user(is_admin=True),
        )
        assert mock_db["projects"].count_documents({}) == 0
        dispatch.assert_not_called()

    def test_an_invalid_template_creates_nothing(self, local_home, mock_db, dispatch):
        template = _local_template()
        template["template"]["template_id"] = "nope"
        with pytest.raises(CodedHTTPException):
            _create(local_home, template)
        assert mock_db["projects"].count_documents({}) == 0
        dispatch.assert_not_called()

    def test_a_prefix_is_created_with_prefix_scans(self, megatest_s3, mock_db, dispatch):
        report = _call(template=_megatest_template(), project_name="From a prefix")
        stored = mock_db["projects"].find_one({"_id": ObjectId(report.project_id)})
        scans = {
            dc["data_collection_tag"]: dc["config"]["scan"]["mode"]
            for wf in stored["workflows"]
            for dc in wf["data_collections"]
        }
        assert scans == {"sheet": "url", "levels": "s3_prefix", "mqc": "s3_prefix"}
        assert stored["template_origin"]["data_root"] == S3_ROOT
        assert dispatch.call_args.kwargs["data_root"] == S3_ROOT


# ── the images an inline template uploads ────────────────────────────────────


def _image_config(**properties) -> dict:
    return {
        "workflows": [
            {
                "name": "main",
                "data_collections": [
                    {
                        "data_collection_tag": "photos",
                        "config": {"type": "image", "dc_specific_properties": dict(properties)},
                    },
                    {
                        "data_collection_tag": "sheet",
                        "config": {"type": "Table", "dc_specific_properties": {"format": "csv"}},
                    },
                ],
            }
        ]
    }


def _folder(config: dict, index: int = 0) -> str | None:
    dc = config["workflows"][0]["data_collections"][index]
    return dc["config"]["dc_specific_properties"].get("s3_base_folder")


class TestDefaultImageFolders:
    def test_an_image_collection_without_a_folder_gets_one_in_the_servers_bucket(self, monkeypatch):
        monkeypatch.setattr(settings.s3, "bucket", "instance-data")
        config = _image_config(image_column="img", local_images_path="/data/run/images")
        from_run._default_image_folders(config)
        folder = _folder(config)
        assert folder.startswith("s3://instance-data/images/")
        assert folder.endswith("/photos")
        # A fresh 12-hex-digit folder, so two projects never share one.
        unique = folder.removeprefix("s3://instance-data/images/").split("/")[0]
        assert len(unique) == 12 and int(unique, 16) >= 0

    def test_a_folder_that_was_given_is_kept(self):
        config = _image_config(image_column="img", s3_base_folder="s3://mine/pictures")
        from_run._default_image_folders(config)
        assert _folder(config) == "s3://mine/pictures"

    @pytest.mark.parametrize("empty", [None, ""])
    def test_an_empty_folder_counts_as_missing(self, empty):
        config = _image_config(image_column="img", s3_base_folder=empty)
        from_run._default_image_folders(config)
        assert _folder(config).startswith(f"s3://{settings.s3.bucket}/images/")

    def test_properties_that_are_missing_altogether_are_made(self):
        config = _image_config()
        del config["workflows"][0]["data_collections"][0]["config"]["dc_specific_properties"]
        from_run._default_image_folders(config)
        assert _folder(config).endswith("/photos")

    def test_the_type_is_read_in_any_case(self):
        config = _image_config(image_column="img")
        config["workflows"][0]["data_collections"][0]["config"]["type"] = "Image"
        from_run._default_image_folders(config)
        assert _folder(config) is not None

    def test_other_types_are_left_alone(self):
        config = _image_config(image_column="img")
        before = json.dumps(config["workflows"][0]["data_collections"][1], sort_keys=True)
        from_run._default_image_folders(config)
        assert json.dumps(config["workflows"][0]["data_collections"][1], sort_keys=True) == before
        assert _folder(config, 1) is None

    def test_each_collection_gets_its_own_folder(self):
        config = _image_config(image_column="img")
        second = json.loads(json.dumps(config["workflows"][0]["data_collections"][0]))
        second["data_collection_tag"] = "scans"
        config["workflows"][0]["data_collections"].append(second)
        from_run._default_image_folders(config)
        assert _folder(config, 0) != _folder(config, 2)
        assert _folder(config, 2).endswith("/scans")

    def test_a_config_without_workflows_is_fine(self):
        from_run._default_image_folders({})
        from_run._default_image_folders({"workflows": [{"name": "empty"}]})

    def test_a_created_project_stores_the_default_but_a_dry_run_plans_without_it(
        self, local_home, mock_db, dispatch
    ):
        template = _template(
            table_dc("sheet", path="images.csv"),
            DcDraft(
                tag="photos",
                type="image",
                mode="single",
                path="images.csv",
                props=ImageProps(image_column="img", local_images_path="images"),
            ),
        )
        planned = _call(
            data_root=str(local_home / "run42"),
            template=template,
            dry_run=True,
            request=_request(),
            user=_user(is_admin=True),
        )
        assert planned.success is True and mock_db["projects"].count_documents({}) == 0

        report = _create(local_home, template)
        stored = mock_db["projects"].find_one({"_id": ObjectId(report.project_id)})
        photos = next(
            dc
            for wf in stored["workflows"]
            for dc in wf["data_collections"]
            if dc["data_collection_tag"] == "photos"
        )
        properties = photos["config"]["dc_specific_properties"]
        assert properties["s3_base_folder"].startswith(f"s3://{settings.s3.bucket}/images/")
        # The model keeps a folder with its trailing slash.
        assert properties["s3_base_folder"].rstrip("/").endswith("/photos")
        assert properties["local_images_path"] == str((local_home / "run42" / "images").resolve())
        # The sheet is a table: untouched.
        sheet = next(
            dc
            for wf in stored["workflows"]
            for dc in wf["data_collections"]
            if dc["data_collection_tag"] == "sheet"
        )
        assert "s3_base_folder" not in sheet["config"]["dc_specific_properties"]
