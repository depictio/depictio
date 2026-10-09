"""What a run's own records say about it, in the shape the API answers it.

``GET /projects/folder_inspect`` (:mod:`run_folders`) and ``POST
/projects/from_run`` (:mod:`from_run`) both carry a :class:`RunInfoSummary`.
The models live here, apart from both: :mod:`run_folders` builds on
:mod:`from_run`, so a model the report of one and the inspection of the other
share could live in neither without an import cycle. How a summary is made
from a run folder is :func:`run_folders._run_info_summary`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RunReportKind = Literal[
    "software_versions", "params", "execution_report", "execution_trace", "pipeline_dag"
]


class RunReportFile(BaseModel):
    """One file the run's engine wrote about the run, such as its execution report.

    ``location`` is its real path, or its ``s3://`` URL. ``size`` is in bytes,
    None when unknown.
    """

    kind: RunReportKind
    location: str
    name: str
    size: int | None = None


class RunTaskSummary(BaseModel):
    """How the tasks of the run ended, counted from its execution trace.

    ``trace`` is the trace read, a real path or an ``s3://`` URL. A task is
    one line of the pipeline (the trace's ``name``, else its ``hash``) and is
    counted once, by the status of its last attempt: ``completed``, ``cached``
    (reused from an earlier launch by ``-resume``), ``failed`` (``FAILED`` or
    ``ABORTED``) or ``other``. ``retried`` counts the tasks that failed and
    then succeeded, already counted as completed or cached. ``partial``: the
    trace was larger than the server reads, so the counts cover its start only.
    """

    trace: str
    total: int
    completed: int
    cached: int
    failed: int
    retried: int
    other: int
    partial: bool = False


class RunInfoSummary(BaseModel):
    """What the run's own records say about it, for display.

    ``params`` holds at most ``run_folders.MAX_RUN_PARAMS`` of the run's
    parameters, by name: a list or a mapping is written as JSON, a long text
    is cut at ``run_folders.MAX_PARAM_CHARS`` characters, and a parameter
    whose name says it holds a credential is shown as
    ``run_folders.HIDDEN_PARAM``. ``params_total`` is how many the run has.
    ``extra`` is the engine's other details that are a single text or number.

    ``tasks`` is None when the run has no execution trace the server could
    read. ``identities_seen`` lists each pipeline and version when the folder
    holds runs of more than one, and ``runs_scanned`` how many run folders were
    read when it holds several (a sequencing-runs layout); None for one run.
    """

    engine: str | None = None
    engine_version: str | None = None
    run_name: str | None = None
    homepage: str | None = None
    params: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    params_total: int = 0
    tools_executed: list[str] = Field(default_factory=list)
    reports: list[RunReportFile] = Field(default_factory=list)
    extra: dict[str, str] = Field(default_factory=dict)
    tasks: RunTaskSummary | None = None
    identities_seen: list[str] = Field(default_factory=list)
    runs_scanned: int | None = None
