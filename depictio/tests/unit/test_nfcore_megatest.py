"""Offline unit tests for scripts/nfcore_megatest.py (all network access is faked)."""

from __future__ import annotations

import email.message
import importlib.util
import io
import json
import re
import sys
import urllib.error
from fnmatch import fnmatchcase
from http.client import IncompleteRead
from pathlib import Path
from types import ModuleType
from xml.etree import ElementTree as ET

import pytest

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "nfcore_megatest.py"
_NFCORE_DIR = Path(__file__).resolve().parents[2] / "projects" / "nf-core"

SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40


@pytest.fixture(scope="module")
def mt() -> ModuleType:
    spec = importlib.util.spec_from_file_location("nfcore_megatest_under_test", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolve string annotations through sys.modules[cls.__module__]
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class _FakeResponse(io.BytesIO):
    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _http_error(code: int, headers: dict[str, str] | None = None) -> urllib.error.HTTPError:
    msg = email.message.Message()
    for key, value in (headers or {}).items():
        msg[key] = value
    return urllib.error.HTTPError("https://x", code, "err", msg, io.BytesIO(b""))


def _index(**pipelines: list[tuple[str, str, str]]) -> dict:
    """``_index(ampliseq=[("2.18.0", SHA_A, "2026-06-17T11:17:18Z"), ...])``."""
    return {
        "remote_workflows": [
            {
                "name": name,
                "releases": [
                    {"tag_name": tag, "tag_sha": sha, "published_at": published}
                    for tag, sha, published in releases
                ],
            }
            for name, releases in pipelines.items()
        ]
    }


class FakeBucket:
    """In-memory stand-in for ``_s3_list`` (ListObjectsV2 XML, pagination, delimiter)."""

    NS = "http://s3.amazonaws.com/doc/2006-03-01/"

    def __init__(self, objects: dict[str, tuple[int, str]]) -> None:
        # full key -> (size, last_modified)
        self.objects = dict(sorted(objects.items()))
        self.calls: list[dict] = []

    def __call__(
        self,
        prefix: str,
        region: str = "eu-west-1",
        delimiter: str | None = None,
        continuation_token: str | None = None,
        max_keys: int | None = None,
    ) -> ET.Element:
        self.calls.append({"prefix": prefix, "delimiter": delimiter, "max_keys": max_keys})
        keys = [k for k in self.objects if k.startswith(prefix)]
        parts = [f'<ListBucketResult xmlns="{self.NS}">']
        if delimiter:
            seen: list[str] = []
            for key in keys:
                rest = key[len(prefix) :]
                if delimiter in rest:
                    common = prefix + rest.split(delimiter, 1)[0] + delimiter
                    if common not in seen:
                        seen.append(common)
            parts.append("<IsTruncated>false</IsTruncated>")
            parts += [f"<CommonPrefixes><Prefix>{c}</Prefix></CommonPrefixes>" for c in seen]
        else:
            start = int(continuation_token or 0)
            page = max_keys or 1000
            chunk = keys[start : start + page]
            truncated = start + page < len(keys)
            parts.append(f"<IsTruncated>{'true' if truncated else 'false'}</IsTruncated>")
            if truncated:
                parts.append(f"<NextContinuationToken>{start + page}</NextContinuationToken>")
            for key in chunk:
                size, lm = self.objects[key]
                parts.append(
                    f"<Contents><Key>{key}</Key><Size>{size}</Size>"
                    f"<LastModified>{lm}</LastModified></Contents>"
                )
        parts.append("</ListBucketResult>")
        return ET.fromstring("".join(parts))


def _run(prefix: str, *files: tuple[str, int], lm: str = "2026-06-17T11:00:00.000Z") -> dict:
    """Objects of a plausible run: dir markers + pipeline_info + the given files."""
    objs = {
        f"{prefix}pipeline_info/": (0, lm),
        f"{prefix}pipeline_info/params_2026-06-17_07-27-43.json": (81461, lm),
        f"{prefix}pipeline_info/params_2026-06-17_11-21-22.json": (81461, lm),
        f"{prefix}pipeline_info/nf_core_x_software_mqc_versions.yml": (2900, lm),
        f"{prefix}pipeline_info/execution_report_2026-06-17.html": (2_400_000, lm),
    }
    for key, size in files:
        objs[f"{prefix}{key}"] = (size, lm)
    return objs


REAL_FILES = [
    ("input/", 0),
    ("input/Samplesheet_full.tsv", 1619),
    ("multiqc/multiqc_data/multiqc.parquet", 136288),
    ("qiime2/barplot/level-2.csv", 962),
    ("qiime2/barplot/level-3.csv", 6100),
    ("qiime2/taxonomy/taxonomy.tsv", 1_500_000),
    ("qiime2/phylogenetic_tree/tree.nwk", 168_200),
    ("qiime2/rel_abundance_tables/rel-table-2.tsv", 935),
]


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def test_http_get_retries_5xx_and_honours_retry_after(
    mt: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    responses = [_http_error(503, {"Retry-After": "7"}), _http_error(500), b"ok"]
    sleeps: list[float] = []

    def fake_open(req, timeout):
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return _FakeResponse(item)

    monkeypatch.setattr(mt, "_urlopen", fake_open)
    assert mt.http_get("https://x", backoff=0.5, sleep=sleeps.append) == b"ok"
    # Retry-After wins for the first retry, exponential backoff for the second.
    assert sleeps == [7.0, 1.0]


def test_http_get_gives_up_and_does_not_retry_404(
    mt: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts: list[int] = []

    def always_503(req, timeout):
        attempts.append(1)
        raise _http_error(503)

    monkeypatch.setattr(mt, "_urlopen", always_503)
    with pytest.raises(urllib.error.HTTPError):
        mt.http_get("https://x", retries=2, sleep=lambda s: None)
    assert len(attempts) == 3  # first try + 2 retries

    attempts.clear()

    def not_found(req, timeout):
        attempts.append(1)
        raise _http_error(404)

    monkeypatch.setattr(mt, "_urlopen", not_found)
    with pytest.raises(urllib.error.HTTPError):
        mt.http_get("https://x", retries=5, sleep=lambda s: None)
    assert len(attempts) == 1


def test_http_get_retries_connection_errors_and_truncated_bodies(
    mt: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    failures = [urllib.error.URLError("reset"), IncompleteRead(b"partial"), TimeoutError()]

    def flaky(req, timeout):
        if failures:
            raise failures.pop(0)
        return _FakeResponse(b"done")

    monkeypatch.setattr(mt, "_urlopen", flaky)
    assert mt.http_get("https://x", sleep=lambda s: None) == b"done"


def test_s3_url_quotes_commas_and_spaces(mt: ModuleType) -> None:
    url = mt.s3_url("differentialabundance/results-x/tables/deseq2_a,deseq2_b/my table.tsv")
    assert url.startswith("https://nf-core-awsmegatests.s3.eu-west-1.amazonaws.com/")
    assert "deseq2_a%2Cdeseq2_b/my%20table.tsv" in url
    assert "," not in url and " " not in url


# ---------------------------------------------------------------------------
# Release index
# ---------------------------------------------------------------------------
def test_release_lookup_accepts_latest_plain_and_v_prefixed(mt: ModuleType) -> None:
    index = _index(
        ampliseq=[
            ("2.17.0", SHA_B, "2026-04-15T16:22:40Z"),
            ("2.18.0", SHA_A, "2026-06-17T11:17:18Z"),
            ("dev", SHA_C, "2026-08-01T00:00:00Z"),
        ]
    )
    assert [r["tag_name"] for r in mt.releases_for(index, "ampliseq")] == ["2.18.0", "2.17.0"]
    assert mt.release_for_version(index, "ampliseq", "latest")["tag_sha"] == SHA_A
    assert mt.release_for_version(index, "ampliseq", None)["tag_sha"] == SHA_A
    assert mt.release_for_version(index, "ampliseq", "2.17.0")["tag_sha"] == SHA_B
    assert mt.release_for_version(index, "ampliseq", "v2.17.0")["tag_sha"] == SHA_B
    assert mt.sha_to_tag(index, "ampliseq", SHA_B) == "2.17.0"
    assert mt.sha_to_tag(index, "ampliseq", "0" * 40) is None
    assert mt.sha_to_tag(None, "ampliseq", SHA_B) is None
    with pytest.raises(mt.MegatestError, match="no release '9.9.9'.*known: 2.18.0, 2.17.0"):
        mt.release_for_version(index, "ampliseq", "9.9.9")
    with pytest.raises(mt.MegatestError, match="not in the nf-core pipelines index"):
        mt.release_for_version(index, "nope", "latest")


def test_load_pipelines_index_precedence_and_cache(
    mt: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    downloads: list[str] = []

    def fake_http_get(url, **kwargs):
        downloads.append(url)
        return json.dumps({"remote_workflows": [{"name": "downloaded", "releases": []}]}).encode()

    monkeypatch.setattr(mt, "http_get", fake_http_get)
    monkeypatch.delenv(mt.PIPELINES_JSON_ENV, raising=False)
    cache = tmp_path / "cache" / "pipelines.json"

    # 1. no cache -> download, and the cache is written
    index = mt.load_pipelines_index(cache_path=cache)
    assert index["remote_workflows"][0]["name"] == "downloaded"
    assert cache.is_file() and downloads == [mt.PIPELINES_JSON_URL]

    # 2. fresh cache -> no download
    cache.write_text(json.dumps({"remote_workflows": [{"name": "cached", "releases": []}]}))
    assert mt.load_pipelines_index(cache_path=cache)["remote_workflows"][0]["name"] == "cached"
    assert len(downloads) == 1

    # 3. stale cache -> download again
    assert (
        mt.load_pipelines_index(cache_path=cache, max_age_s=0)["remote_workflows"][0]["name"]
        == "downloaded"
    )
    assert len(downloads) == 2

    # 4. explicit path and env var beat everything (no download)
    explicit = tmp_path / "explicit.json"
    explicit.write_text(json.dumps({"remote_workflows": [{"name": "explicit", "releases": []}]}))
    assert mt.load_pipelines_index(explicit, cache_path=cache)["remote_workflows"][0]["name"] == (
        "explicit"
    )
    monkeypatch.setenv(mt.PIPELINES_JSON_ENV, str(explicit))
    assert mt.load_pipelines_index(cache_path=cache)["remote_workflows"][0]["name"] == "explicit"
    assert len(downloads) == 2

    # 5. download failure with a stale cache falls back to the stale copy
    monkeypatch.delenv(mt.PIPELINES_JSON_ENV)

    def failing_http_get(url, **kwargs):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(mt, "http_get", failing_http_get)
    assert (
        mt.load_pipelines_index(cache_path=cache, max_age_s=0)["remote_workflows"][0]["name"]
        == "downloaded"
    )


# ---------------------------------------------------------------------------
# Listing, run discovery, empty-run heuristic
# ---------------------------------------------------------------------------
def test_list_result_prefixes_keeps_only_40_hex_release_dirs(
    mt: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    bucket = FakeBucket(
        {
            f"chipseq/results-{SHA_A}/x.txt": (1, ""),
            f"chipseq/results-{SHA_B}/y.txt": (1, ""),
            "chipseq/results-dev/z.txt": (1, ""),
            f"chipseq/results-test-{SHA_C}/w.txt": (1, ""),
            "chipseq/results-abc123/short.txt": (1, ""),
            "chipseq/README": (1, ""),
        }
    )
    monkeypatch.setattr(mt, "_s3_list", bucket)
    assert mt.list_result_prefixes("chipseq") == [
        f"chipseq/results-{SHA_A}/",
        f"chipseq/results-{SHA_B}/",
    ]
    assert bucket.calls[0]["delimiter"] == "/"


def test_list_s3_objects_paginates_and_honours_limit(
    mt: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    objects = {f"p/f{i:02d}.tsv": (10, "2026-01-01T00:00:00.000Z") for i in range(7)}
    bucket = FakeBucket(objects)
    monkeypatch.setattr(mt, "_s3_list", bucket)

    # full walk: the fake serves at most 1000 per page, so one call here
    listing = mt.list_s3_objects("p/")
    assert [o.key for o in listing.objects] == [f"f{i:02d}.tsv" for i in range(7)]
    assert listing.truncated is False

    # limit smaller than the run: max-keys is passed down and the walk stops early
    bucket.calls.clear()
    listing = mt.list_s3_objects("p/", limit=3)
    assert len(listing.objects) == 3 and listing.truncated is True
    assert bucket.calls[0]["max_keys"] == 3

    # limit above the run size never reports truncation
    listing = mt.list_s3_objects("p/", limit=50)
    assert len(listing.objects) == 7 and listing.truncated is False
    # compatibility wrappers keep the old shapes
    assert mt.list_objects("p/")[0] == ("f00.tsv", 10)
    assert mt.list_keys("p/")[-1] == "f06.tsv"


def test_run_stats_and_empty_run_heuristic(mt: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    prefix = f"methylseq/results-{SHA_A}/"
    truncated_sync = _run(
        prefix,
        ("bismark/", 0),
        ("bismark/a.bam", 5_000_000_000),
        ("bismark/b.bam", 15_800_000_000),
        ("bismark/c.bam", 6_500_000_000),
        ("bismark/d.txt.gz", 5_100_000_000),
        ("bismark/e.txt.gz", 5_200_000_000),
        ("multiqc/", 0),
    )
    monkeypatch.setattr(mt, "_s3_list", FakeBucket(truncated_sync))
    stats = mt.run_stats(prefix)
    # dir markers and pipeline_info/ never count as data
    assert stats.n_objects == 12 and stats.n_data_objects == 5 and stats.n_small_data_objects == 0
    assert stats.top_dirs == ["bismark", "multiqc", "pipeline_info"]
    assert stats.has_multiqc_parquet is False
    assert mt.is_empty_run(stats) is True  # 5 giant intermediates, no small report

    monkeypatch.setattr(mt, "_s3_list", FakeBucket(_run(prefix)))
    assert mt.is_empty_run(mt.run_stats(prefix)) is True  # pipeline_info only

    monkeypatch.setattr(mt, "_s3_list", FakeBucket(_run(prefix, *REAL_FILES)))
    stats = mt.run_stats(prefix)
    assert stats.n_data_objects == 7 and stats.n_small_data_objects == 7
    assert stats.has_multiqc_parquet is True
    assert stats.multiqc_parquet_keys == ["multiqc/multiqc_data/multiqc.parquet"]
    assert mt.is_empty_run(stats) is False
    assert mt.is_empty_run(stats, min_data_objects=8) is True


def test_resolve_run_verifies_prefix_and_rejects_empty_runs(
    mt: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    index = _index(
        methylseq=[
            ("4.2.0", SHA_A, "2025-12-12T00:00:00Z"),
            ("4.0.0", SHA_B, "2025-07-04T00:00:00Z"),
            ("2.3.0", SHA_C, "2022-12-17T00:00:00Z"),
        ]
    )
    bucket = FakeBucket(
        {
            **_run(f"methylseq/results-{SHA_A}/"),  # 4.2.0: pipeline_info only
            **_run(f"methylseq/results-{SHA_C}/", *REAL_FILES, lm="2022-12-17T00:00:00.000Z"),
        }
    )
    monkeypatch.setattr(mt, "_s3_list", bucket)

    # empty release run -> error carries the fallback table with the real run
    with pytest.raises(mt.MegatestError) as excinfo:
        mt.resolve_run("methylseq", "4.2.0", index=index)
    assert "4.2.0" in excinfo.value.reason and "empty, failed or truncated" in excinfo.value.reason
    table = excinfo.value.fallback
    assert f"methylseq/results-{SHA_C}/" in table and "2.3.0" in table
    assert "parquet" in table and "yes" in table
    assert f"methylseq/results-{SHA_B}/" not in table  # never synced: no prefix, no row
    assert table in str(excinfo.value)

    # missing prefix (release never ran)
    with pytest.raises(mt.MegatestError, match="no megatest run"):
        mt.resolve_run("methylseq", "4.0.0", index=index)

    # the real run resolves, with tag + stats
    run = mt.resolve_run("methylseq", "2.3.0", index=index)
    assert run.prefix == f"methylseq/results-{SHA_C}/"
    assert run.tag == "2.3.0" and run.results_sha == SHA_C
    assert run.stats is not None and run.stats.has_multiqc_parquet
    assert run.root_prefix == run.prefix and run.s3_uri.endswith(run.prefix)

    # explicit hash wins over the version and is still verified
    run = mt.resolve_run("methylseq", "4.2.0", results_hash=f"results-{SHA_C}", index=index)
    assert run.results_sha == SHA_C and run.tag == "2.3.0"

    # run_root must exist below the prefix
    run = mt.resolve_run("methylseq", "2.3.0", run_root="qiime2", index=index)
    assert run.run_root == "qiime2/" and run.root_prefix == f"methylseq/results-{SHA_C}/qiime2/"
    with pytest.raises(mt.MegatestError, match="run_root 'aligner_star_salmon/' not found"):
        mt.resolve_run("methylseq", "2.3.0", run_root="aligner_star_salmon/", index=index)

    # newest_nonempty_run skips the empty 4.2.0 prefix
    best = mt.newest_nonempty_run("methylseq", index=index)
    assert best is not None and best.tag == "2.3.0"


# ---------------------------------------------------------------------------
# Manifest: key expansion, renames, fetch
# ---------------------------------------------------------------------------
def _objs(*keys: str) -> list:
    return [(k, 0 if k.endswith("/") else 10, "2026-01-01T00:00:00.000Z") for k in keys]


def test_expand_keys_exact_glob_markers_and_unmatched(mt: ModuleType) -> None:
    objects = [
        mt.S3Object(k, s, lm)
        for k, s, lm in _objs(
            "input/",
            "input/Samplesheet_full.tsv",
            "qiime2/barplot/level-2.csv",
            "qiime2/barplot/level-3.csv",
            "qiime2/ancombc/differentials/Category-habitat-level-2/lfc_slice.csv",
            "qiime2/ancombc/differentials/Category-habitat-level-2/w_slice.csv",
        )
    ]
    matched, unmatched = mt.expand_keys(
        [
            "input/Samplesheet_full.tsv",
            "qiime2/barplot/*.csv",
            "qiime2/barplot/level-2.csv",  # duplicate of a glob hit: deduplicated
            "qiime2/ancombc/differentials/Category-habitat-level-2/*_slice.csv",
            "input/*",  # only the dir marker is under input/ besides the samplesheet
            "missing/file.tsv",
            "nothing/*.csv",
        ],
        objects,
    )
    assert [o.key for o in matched] == [
        "input/Samplesheet_full.tsv",
        "qiime2/barplot/level-2.csv",
        "qiime2/barplot/level-3.csv",
        "qiime2/ancombc/differentials/Category-habitat-level-2/lfc_slice.csv",
        "qiime2/ancombc/differentials/Category-habitat-level-2/w_slice.csv",
    ]
    assert unmatched == ["missing/file.tsv", "nothing/*.csv"]


def test_apply_renames_newest_wins_and_leaves_other_keys(mt: ModuleType) -> None:
    objects = [
        mt.S3Object("pipeline_info/params_2026-06-17_07-27-43.json", 1, "2026-06-17T07:30:00Z"),
        mt.S3Object("pipeline_info/params_2026-06-17_11-21-22.json", 1, "2026-06-17T11:30:00Z"),
        mt.S3Object("pipeline_info/nf_core_ampliseq_software_mqc_versions.yml", 1, "x"),
        mt.S3Object("qiime2/barplot/level-2.csv", 1, "x"),
    ]
    renamed = mt.apply_renames(objects)
    assert [(o.key, target) for o, target in renamed] == [
        ("pipeline_info/params_2026-06-17_11-21-22.json", "pipeline_info/params.json"),
        (
            "pipeline_info/nf_core_ampliseq_software_mqc_versions.yml",
            "pipeline_info/software_versions.yml",
        ),
        ("qiime2/barplot/level-2.csv", "qiime2/barplot/level-2.csv"),
    ]
    # manifest renames extend the defaults
    custom = {**mt.DEFAULT_RENAMES, "qiime2/barplot/level-2.csv": "phylum.csv"}
    assert mt.apply_renames(objects[-1:], custom) == [(objects[-1], "phylum.csv")]


def test_fetch_run_strips_run_root_and_mirrors_prefix_keys(
    mt: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    prefix = f"rnaseq/results-{SHA_A}/"
    bucket = FakeBucket(
        _run(
            prefix,
            ("aligner_star_salmon/", 0),
            ("aligner_star_salmon/multiqc/star_salmon/multiqc_report_data/multiqc.parquet", 500),
            ("aligner_star_salmon/star_salmon/salmon.merged.gene_tpm.tsv", 900),
            ("aligner_star_salmon/star_salmon/huge.bam", 2_000_000_000),
            ("aligner_star_rsem/star_rsem/salmon.merged.gene_tpm.tsv", 900),
        )
    )
    monkeypatch.setattr(mt, "_s3_list", bucket)
    downloaded: list[tuple[str, str, Path, int]] = []

    def fake_download(prefix_, rel_key, dest, region="eu-west-1", size=None):
        downloaded.append((prefix_, rel_key, Path(dest), size))
        return True

    monkeypatch.setattr(mt, "download_object", fake_download)
    run = mt.ResolvedRun("rnaseq", SHA_A, prefix, "3.26.0", "aligner_star_salmon/")
    summary = mt.fetch_run(
        run,
        tmp_path,
        keys=["multiqc/star_salmon/multiqc_report_data/multiqc.parquet", "star_salmon/*"],
        prefix_keys=["pipeline_info/params_*.json"],
        max_file_mb=1000,
    )
    by_target = {f.dest.relative_to(tmp_path).as_posix(): f for f in summary.files}
    assert set(by_target) == {
        "multiqc/star_salmon/multiqc_report_data/multiqc.parquet",
        "star_salmon/salmon.merged.gene_tpm.tsv",
        "star_salmon/huge.bam",
        "pipeline_info/params.json",  # outside the run root, newest params file
    }
    assert by_target["star_salmon/huge.bam"].action == "too-large"
    assert by_target["pipeline_info/params.json"].key == (
        "pipeline_info/params_2026-06-17_11-21-22.json"
    )
    # downloads address the object by its full key below the results prefix
    assert (prefix, "aligner_star_salmon/star_salmon/salmon.merged.gene_tpm.tsv") in {
        (p, k) for p, k, _, _ in downloaded
    }
    assert all(p == prefix for p, _, _, _ in downloaded)
    assert not any("huge.bam" in k for _, k, _, _ in downloaded)
    assert summary.count("downloaded") == 3 and summary.count("too-large") == 1
    assert summary.total_bytes == 500 + 900 + 81461
    assert summary.unmatched == []


def test_fetch_run_dry_run_writes_nothing_and_reports_unmatched(
    mt: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    prefix = f"ampliseq/results-{SHA_A}/"
    monkeypatch.setattr(mt, "_s3_list", FakeBucket(_run(prefix, *REAL_FILES)))

    def must_not_download(*args, **kwargs):
        raise AssertionError("dry run must not download")

    monkeypatch.setattr(mt, "download_object", must_not_download)
    run = mt.ResolvedRun("ampliseq", SHA_A, prefix, "2.18.0", "")
    dest = tmp_path / "megatest"
    summary = mt.fetch_run(run, dest, keys=["qiime2/barplot/*.csv", "nope/*.tsv"], dry_run=True)
    assert summary.dry_run is True
    assert [f.action for f in summary.files] == ["planned", "planned"]
    assert summary.unmatched == ["nope/*.tsv"]
    assert not dest.exists()


def test_fetch_run_refuses_a_key_that_escapes_the_destination(
    mt: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A bucket key that is absolute or climbs out must not be written.

    Path joining drops the destination when the right operand is absolute, so
    without the guard such a key would land outside the fetch directory.
    """
    prefix = f"ampliseq/results-{SHA_A}/"
    for hostile in ("../escape.tsv", "/etc/escape.tsv"):
        monkeypatch.setattr(mt, "_s3_list", FakeBucket(_run(prefix, (hostile, 12))))

        def must_not_download(*args, **kwargs):
            raise AssertionError("a rejected key must not be downloaded")

        monkeypatch.setattr(mt, "download_object", must_not_download)
        run = mt.ResolvedRun("ampliseq", SHA_A, prefix, "2.18.0", "")
        dest = tmp_path / "megatest"
        with pytest.raises(mt.MegatestError, match="below the destination"):
            mt.fetch_run(run, dest, keys=["*escape.tsv"])
        assert not (tmp_path / "escape.tsv").exists()
        assert not Path("/etc/escape.tsv").exists()


def test_download_object_skips_same_size_and_leaves_no_part_file(
    mt: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []

    def fake_http_get(url, **kwargs):
        calls.append(url)
        return b"0123456789"

    monkeypatch.setattr(mt, "http_get", fake_http_get)
    dest = tmp_path / "a" / "b.tsv"
    assert mt.download_object("p/", "a/b.tsv", dest, size=10) is True
    assert dest.read_bytes() == b"0123456789"
    assert not list(tmp_path.rglob("*.part"))
    assert mt.download_object("p/", "a/b.tsv", dest, size=10) is False  # kept
    assert mt.download_object("p/", "a/b.tsv", dest, size=99) is True  # size differs: refetch
    assert len(calls) == 2 and calls[0].endswith("/p/a/b.tsv")


# ---------------------------------------------------------------------------
# Manifest validation + shipped manifests
# ---------------------------------------------------------------------------
_VALID = {
    "pipeline": "ampliseq",
    "version": "2.18.0",
    "results_sha": SHA_A,
    "run_root": "",
    "multiqc": {"version": "1.34", "parquet": "multiqc/multiqc_data/multiqc.parquet"},
    "keys": ["multiqc/multiqc_data/multiqc.parquet", "qiime2/barplot/*.csv"],
}


def test_manifest_from_dict_accepts_valid_and_normalizes(mt: ModuleType) -> None:
    manifest = mt.manifest_from_dict({**_VALID, "run_root": "aligner_star_salmon"})
    assert manifest.run_root == "aligner_star_salmon/"
    assert manifest.multiqc == {
        "version": "1.34",
        "parquet": "multiqc/multiqc_data/multiqc.parquet",
        "reprocess": False,
    }
    assert manifest.prefix_keys == [] and manifest.renames == {}
    assert manifest.effective_renames == mt.DEFAULT_RENAMES
    assert (
        mt.manifest_path("ampliseq", "2.18.0")
        .as_posix()
        .endswith("projects/nf-core/ampliseq/2.18.0/megatest.yaml")
    )


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ({"pipeline": None}, "'pipeline' is required"),
        ({"version": 2.18}, "'version' is required and must be a quoted string"),
        ({"results_sha": "abc"}, "40-char lowercase hex"),
        ({"results_sha": SHA_A.upper()}, "40-char lowercase hex"),
        ({"keys": "multiqc/x.parquet"}, "'keys' must be a list"),
        ({"keys": ["/abs/path.tsv"]}, "must be a relative path"),
        ({"keys": ["../escape.tsv"]}, "must be a relative path"),
        ({"prefix_keys": [""]}, "'prefix_keys' must be a list of non-empty strings"),
        ({"run_root": "/aligner"}, "'run_root' must be a relative directory"),
        ({"multiqc": {"version": 1.34}}, "'multiqc.version' must be a quoted string"),
        ({"multiqc": {"parquet": "/x.parquet"}}, "'multiqc.parquet' must be a relative path"),
        ({"multiqc": {"reprocess": "yes"}}, "'multiqc.reprocess' must be true or false"),
        ({"multiqc": {"bogus": 1}}, "'multiqc' must be a mapping with keys"),
        ({"renames": {"a/*": "/abs"}}, "'renames' must map key globs to relative paths"),
        ({"typo_field": 1}, "unknown field"),
    ],
)
def test_manifest_from_dict_rejects_invalid(mt: ModuleType, patch: dict, message: str) -> None:
    with pytest.raises(ValueError, match=re.escape(message)):
        mt.manifest_from_dict({**_VALID, **patch})
    with pytest.raises(ValueError, match="top level must be a mapping"):
        mt.manifest_from_dict(["not", "a", "mapping"])


def test_simple_yaml_parser_covers_manifest_subset(mt: ModuleType) -> None:
    text = """
# comment
pipeline: ampliseq   # inline comment
version: "2.18.0"
results_sha: null
run_root: ""
multiqc:
  version: '1.34'
  parquet: multiqc/multiqc_data/multiqc.parquet
  reprocess: false
keys:
  - a/*.tsv
  - "b, c/d e.csv"
prefix_keys: []
renames: {}
empty_value:
post_fetch_help: |
  line one
    indented two

  after blank
tail: ~
"""
    parsed = mt._SimpleYaml(text).parse()
    assert parsed == {
        "pipeline": "ampliseq",
        "version": "2.18.0",
        "results_sha": None,
        "run_root": "",
        "multiqc": {
            "version": "1.34",
            "parquet": "multiqc/multiqc_data/multiqc.parquet",
            "reprocess": False,
        },
        "keys": ["a/*.tsv", "b, c/d e.csv"],
        "prefix_keys": [],
        "renames": {},
        "empty_value": None,
        "post_fetch_help": "line one\n  indented two\n\nafter blank\n",
        "tail": None,
    }
    with pytest.raises(ValueError, match="unexpected indentation"):
        mt._SimpleYaml("a: 1\n   b: 2\n").parse()


def _shipped_manifests() -> list[Path]:
    return sorted(_NFCORE_DIR.glob("*/*/megatest.yaml"))


def _multiqc_dc_patterns(template: dict) -> list[str]:
    patterns: list[str] = []
    for workflow in template.get("workflows", []):
        for dc in workflow.get("data_collections", []):
            config = dc.get("config", {})
            if config.get("type") == "MultiQC":
                patterns.append(config["scan"]["scan_parameters"]["regex_config"]["pattern"])
    return patterns


def test_shipped_manifests_exist_for_reference_templates() -> None:
    names = {f"{p.parents[1].name}/{p.parent.name}" for p in _shipped_manifests()}
    assert {"ampliseq/2.18.0", "variantbenchmarking/1.4.0"} <= names


@pytest.mark.parametrize("manifest_file", _shipped_manifests(), ids=lambda p: p.parent.name)
def test_simple_yaml_parser_agrees_with_pyyaml_on_shipped_manifests(
    mt: ModuleType, manifest_file: Path
) -> None:
    yaml = pytest.importorskip("yaml")
    text = manifest_file.read_text(encoding="utf-8")
    assert mt._SimpleYaml(text).parse() == yaml.safe_load(text)


@pytest.mark.parametrize(
    "manifest_file", _shipped_manifests(), ids=lambda p: f"{p.parents[1].name}-{p.parent.name}"
)
def test_every_shipped_manifest_is_consistent(mt: ModuleType, manifest_file: Path) -> None:
    yaml = pytest.importorskip("yaml")
    manifest = mt.load_manifest(manifest_file)  # validates shape, sha, relative keys
    version_dir = manifest_file.parent
    assert manifest.pipeline == version_dir.parent.name
    assert manifest.version == version_dir.name
    assert manifest.results_sha is None or re.fullmatch(r"[0-9a-f]{40}", manifest.results_sha)
    assert manifest.keys, "a manifest must list at least one key"
    for key in manifest.keys + manifest.prefix_keys:
        assert mt.is_relative_key(key)
    # Provenance is always part of the subset, because the CLI introspects it and the
    # template's `provenance` block reads it. Which file carries it depends on the
    # pipeline's era: DSL2 runs write a timestamped params JSON, while pre-DSL2 runs
    # (chipseq 1.2.0, atacseq 1.2.x, cutandrun 3.1) write only a software-versions
    # table. Requiring the params JSON alone would reject every older run, which is
    # exactly the set that has to be reprocessed and templated from an older release.
    provenance_names = (
        "pipeline_info/params_2026-01-01_00-00-00.json",
        "pipeline_info/software_versions.yml",
        "pipeline_info/software_versions.csv",
    )
    assert any(
        fnmatchcase(name, k)
        for k in manifest.keys + manifest.prefix_keys
        for name in provenance_names
    ), "the manifest fetches no provenance file (params JSON or software versions)"

    template = yaml.safe_load((version_dir / "template.yaml").read_text(encoding="utf-8"))
    patterns = _multiqc_dc_patterns(template)
    parquet = manifest.multiqc["parquet"]
    if parquet is None:
        assert not patterns, "template declares a MultiQC DC but the manifest names no parquet"
        assert manifest.multiqc["version"] is None
    else:
        assert parquet.endswith("multiqc.parquet")
        if manifest.multiqc["reprocess"]:
            # A reprocessed run has no parquet to fetch: its report predates the
            # parquet era, so `multiqc.parquet` names the file that
            # depictio.dev_scripts.multiqc_reprocess writes into the fetched tree
            # afterwards. Requiring a key for it would make the manifest claim the
            # bucket publishes a file it does not.
            assert not any(k == parquet or fnmatchcase(parquet, k) for k in manifest.keys), (
                "multiqc.reprocess is set, so multiqc.parquet is produced locally "
                "and must not also be listed as a fetched key"
            )
            assert "multiqc_reprocess" in (manifest.post_fetch_help or ""), (
                "a reprocessed manifest must tell the caller how to produce the parquet"
            )
        else:
            assert any(k == parquet or fnmatchcase(parquet, k) for k in manifest.keys), (
                "multiqc.parquet must be fetched by one of the manifest keys"
            )
        assert patterns, "manifest names a parquet but the template has no MultiQC DC"
        assert any(re.search(p, parquet) for p in patterns), (
            f"template MultiQC pattern(s) {patterns} do not match {parquet}"
        )
        assert re.fullmatch(r"\d+\.\d+(\.\d+)?", manifest.multiqc["version"] or "")
    if manifest.multiqc["reprocess"]:
        assert parquet is not None

    wrapper = version_dir / "download_test_data.sh"
    if wrapper.is_file() and "nfcore_megatest.py" in wrapper.read_text(encoding="utf-8"):
        text = wrapper.read_text(encoding="utf-8")
        assert f"--pipeline {manifest.pipeline}" in text
        assert f"--version {manifest.version}" in text
        assert "set -euo pipefail" in text


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def test_cli_resolve_exit_codes_and_fallback_table(
    mt: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    index = _index(
        methylseq=[
            ("4.2.0", SHA_A, "2025-12-12T00:00:00Z"),
            ("2.3.0", SHA_C, "2022-12-17T00:00:00Z"),
        ]
    )
    index_file = tmp_path / "pipelines.json"
    index_file.write_text(json.dumps(index))
    bucket = FakeBucket(
        {
            **_run(f"methylseq/results-{SHA_A}/"),
            **_run(f"methylseq/results-{SHA_C}/", *REAL_FILES),
        }
    )
    monkeypatch.setattr(mt, "_s3_list", bucket)

    rc = mt.main(
        ["resolve", "--pipeline", "methylseq", "--version", "2.3.0", "--index", str(index_file)]
    )
    out = capsys.readouterr()
    assert rc == 0
    assert f"prefix     methylseq/results-{SHA_C}/" in out.out
    assert "tag        2.3.0" in out.out

    rc = mt.main(
        ["resolve", "--pipeline", "methylseq", "--version", "4.2.0", "--index", str(index_file)]
    )
    out = capsys.readouterr()
    assert rc == 3
    assert "empty, failed or truncated" in out.err
    assert f"methylseq/results-{SHA_C}/" in out.err and "2.3.0" in out.err  # fallback table

    rc = mt.main(
        [
            "resolve",
            "--pipeline",
            "methylseq",
            "--version",
            "2.3.0",
            "--index",
            str(index_file),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["results_sha"] == SHA_C and payload["stats"]["has_multiqc_parquet"] is True


def test_cli_fetch_dry_run_uses_manifest(
    mt: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    index = _index(ampliseq=[("2.18.0", SHA_A, "2026-06-17T11:17:18Z")])
    index_file = tmp_path / "pipelines.json"
    index_file.write_text(json.dumps(index))
    monkeypatch.setattr(mt, "_s3_list", FakeBucket(_run(f"ampliseq/results-{SHA_A}/", *REAL_FILES)))
    manifest = tmp_path / "megatest.yaml"
    manifest.write_text(
        'pipeline: ampliseq\nversion: "2.18.0"\nresults_sha: null\n'
        "keys:\n  - pipeline_info/params_*.json\n  - qiime2/barplot/*.csv\n"
        "post_fetch_help: |\n  run it on {dest}\n"
    )
    dest = tmp_path / "out"
    rc = mt.main(
        [
            "fetch",
            "--pipeline",
            "ampliseq",
            "--version",
            "2.18.0",
            "--manifest",
            str(manifest),
            "--dest",
            str(dest),
            "--index",
            str(index_file),
            "--dry-run",
        ]
    )
    out = capsys.readouterr()
    assert rc == 0
    assert "plan" in out.out and "pipeline_info/params.json" in out.out
    assert "qiime2/barplot/level-3.csv" in out.out
    assert "3 file(s)" in out.out
    assert "run it on" not in out.out  # post-fetch help only after a real fetch
    assert not dest.exists()
