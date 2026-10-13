"""The sandbox boundary a code-mode figure runs inside.

``SimpleCodeExecutor`` hands user Python a copy of ``df`` and the plotting
libraries so a figure can be built, and nothing more. These tests pin the two
halves of that boundary:

* **It fails safely** — reading or writing server files, walking a module
  global to arbitrary code (``pd.io.common.os``), the numpy load/save family,
  and the ``str.format`` escape RestrictedPython itself blocks.
* **Legitimate figures still run** — the frame-to-Plotly handoffs
  (``to_pandas`` / ``to_list`` / ``to_dicts``), polars and pandas aggregation,
  the palette submodules (``px.colors``) and ``np.random`` the allowlist keeps,
  and post-figure customisation.

Lives next to ``test_code_executor_builtins.py``; same in-memory frame, no
database, no HTTP.
"""

from __future__ import annotations

import os
import pickle
from contextlib import contextmanager

import polars as pl
import pytest

from depictio.api.v1.services.figure.code_executor import SimpleCodeExecutor

FIG = "fig = px.scatter(df.to_pandas(), x='x', y='y')"


def _frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "x": [1.0, 4.0, 2.0],
            "y": [3.0, 1.0, 5.0],
            "variety": ["a", "b", "a"],
        }
    )


@pytest.fixture
def secret_csv(tmp_path):
    p = tmp_path / "secret.csv"
    p.write_text("token\nTOPSECRET\n")
    return str(p)


@pytest.fixture
def secret_pickle(tmp_path):
    p = tmp_path / "secret.pkl"
    with open(p, "wb") as fh:
        pickle.dump({"a": 1}, fh)
    return str(p)


# --- fails safely -----------------------------------------------------------


def test_pl_read_csv_is_denied(secret_csv):
    code = f"leak = pl.read_csv({secret_csv!r}).row(0)\n{FIG}"
    ok, _, message = SimpleCodeExecutor().execute_code(code, _frame())
    assert not ok
    assert "read_csv" in message


def test_pl_scan_csv_is_denied(secret_csv):
    code = f"leak = pl.scan_csv({secret_csv!r}).collect().row(0)\n{FIG}"
    ok, _, message = SimpleCodeExecutor().execute_code(code, _frame())
    assert not ok
    assert "scan_csv" in message


def test_pd_read_pickle_is_denied(secret_pickle):
    code = f"leak = pd.read_pickle({secret_pickle!r})\n{FIG}"
    ok, _, message = SimpleCodeExecutor().execute_code(code, _frame())
    assert not ok
    assert "read_pickle" in message


def test_df_to_csv_to_a_path_is_denied(tmp_path):
    out = str(tmp_path / "out.csv")
    code = f"{FIG}\ndf.to_pandas().to_csv({out!r})"
    ok, _, message = SimpleCodeExecutor().execute_code(code, _frame())
    assert not ok
    assert "to_csv" in message
    assert not os.path.exists(out)


def test_df_write_csv_to_a_path_is_denied(tmp_path):
    out = str(tmp_path / "out.csv")
    code = f"{FIG}\ndf.write_csv({out!r})"
    ok, _, message = SimpleCodeExecutor().execute_code(code, _frame())
    assert not ok
    assert "write_csv" in message
    assert not os.path.exists(out)


def test_fig_write_html_is_denied(tmp_path):
    out = str(tmp_path / "out.html")
    code = f"{FIG}\nfig.write_html({out!r})"
    ok, _, message = SimpleCodeExecutor().execute_code(code, _frame())
    assert not ok
    assert "write_html" in message
    assert not os.path.exists(out)


def test_fig_show_is_denied():
    code = f"{FIG}\nfig.show()"
    ok, _, message = SimpleCodeExecutor().execute_code(code, _frame())
    assert not ok
    assert "show" in message


def test_module_walk_to_os_is_denied():
    """pd.io.common.os — the no-underscore walk to the filesystem and exec."""
    code = f"o = pd.io.common.os\nleak = o.getcwd()\n{FIG}"
    ok, _, message = SimpleCodeExecutor().execute_code(code, _frame())
    assert not ok
    assert "module" in message.lower()


def test_np_load_is_denied(secret_pickle):
    code = f"leak = np.load({secret_pickle!r}, allow_pickle=True)\n{FIG}"
    ok, _, message = SimpleCodeExecutor().execute_code(code, _frame())
    assert not ok
    assert "load" in message


def test_np_save_to_a_path_is_denied(tmp_path):
    out = str(tmp_path / "arr.npy")
    code = f"a = np.asarray([1, 2, 3])\nnp.save({out!r}, a)\n{FIG}"
    ok, _, message = SimpleCodeExecutor().execute_code(code, _frame())
    assert not ok
    assert "save" in message
    assert not os.path.exists(out)


def test_str_format_escape_is_denied():
    """RestrictedPython's own ``str.format`` escape, kept by ``safer_getattr``."""
    code = f"leak = '{{0.x}}'.format(df)\n{FIG}"
    ok, _, message = SimpleCodeExecutor().execute_code(code, _frame())
    assert not ok


def test_import_is_still_refused():
    """The allowlist grew; the sandbox did not open."""
    ok, _, message = SimpleCodeExecutor().execute_code(f"import os\n{FIG}", _frame())
    assert not ok
    assert "import" in message.lower()


# --- second-pass denylist vectors (a name denylist alone leaks) -------------
#
# Each of these worked before the second hardening pass. Several ran their side
# effect (wrote a file / executed a command) even while the analyzer reported
# failure, so the fixtures assert the FILE / SENTINEL is absent, not merely that
# ``ok`` is False.


def test_pl_config_save_to_file_is_denied(tmp_path):
    out = str(tmp_path / "cfg.json")
    code = f"pl.Config.save_to_file({out!r})\n{FIG}"
    ok, _, _ = SimpleCodeExecutor().execute_code(code, _frame())
    assert not ok
    assert not os.path.exists(out)


def test_pl_config_load_from_file_is_denied(tmp_path):
    out = str(tmp_path / "cfg.json")
    code = f"pl.Config.load_from_file({out!r})\n{FIG}"
    ok, _, message = SimpleCodeExecutor().execute_code(code, _frame())
    assert not ok
    assert "load_from_file" in message


def test_pd_excelwriter_is_denied(tmp_path):
    out = str(tmp_path / "x.xlsx")
    code = f"w = pd.ExcelWriter({out!r})\n{FIG}"
    ok, _, message = SimpleCodeExecutor().execute_code(code, _frame())
    assert not ok
    assert "ExcelWriter" in message
    assert not os.path.exists(out)


def test_pd_excelfile_is_denied(secret_csv):
    code = f"e = pd.ExcelFile({secret_csv!r})\n{FIG}"
    ok, _, message = SimpleCodeExecutor().execute_code(code, _frame())
    assert not ok
    assert "ExcelFile" in message


def test_pd_hdfstore_is_denied(tmp_path):
    out = str(tmp_path / "x.h5")
    code = f"s = pd.HDFStore({out!r}, mode='w')\n{FIG}"
    ok, _, message = SimpleCodeExecutor().execute_code(code, _frame())
    assert not ok
    assert "HDFStore" in message
    assert not os.path.exists(out)


def test_polars_serialize_is_denied(tmp_path):
    out = str(tmp_path / "df.bin")
    code = f"df.serialize({out!r})\n{FIG}"
    ok, _, _ = SimpleCodeExecutor().execute_code(code, _frame())
    assert not ok
    assert not os.path.exists(out)


def test_polars_lazyframe_serialize_is_denied(tmp_path):
    out = str(tmp_path / "lf.bin")
    code = f"df.lazy().serialize({out!r})\n{FIG}"
    ok, _, _ = SimpleCodeExecutor().execute_code(code, _frame())
    assert not ok
    assert not os.path.exists(out)


def test_polars_deserialize_is_denied(secret_pickle):
    code = f"leak = pl.DataFrame.deserialize({secret_pickle!r})\n{FIG}"
    ok, _, message = SimpleCodeExecutor().execute_code(code, _frame())
    assert not ok
    assert "deserialize" in message


def test_ndarray_dump_is_denied(tmp_path):
    out = str(tmp_path / "a.pkl")
    code = f"a = np.asarray([1, 2, 3])\na.dump({out!r})\n{FIG}"
    ok, _, message = SimpleCodeExecutor().execute_code(code, _frame())
    assert not ok
    assert "dump" in message
    assert not os.path.exists(out)


def test_ndarray_dumps_is_denied():
    code = f"a = np.asarray([1, 2, 3])\nb = a.dumps()\n{FIG}"
    ok, _, message = SimpleCodeExecutor().execute_code(code, _frame())
    assert not ok
    assert "dumps" in message


def test_np_lib_module_is_denied():
    code = f"m = np.lib\n{FIG}"
    ok, _, message = SimpleCodeExecutor().execute_code(code, _frame())
    assert not ok
    assert "module" in message.lower()


def test_pd_to_string_buf_is_denied(tmp_path):
    out = str(tmp_path / "s.txt")
    code = f"df.to_pandas().to_string(buf={out!r})\n{FIG}"
    ok, _, _ = SimpleCodeExecutor().execute_code(code, _frame())
    assert not ok
    assert not os.path.exists(out)


def test_pd_set_option_is_denied():
    code = f"pd.set_option('io.excel.xlsx.writer', 'x')\n{FIG}"
    ok, _, message = SimpleCodeExecutor().execute_code(code, _frame())
    assert not ok
    assert "set_option" in message


def test_np_datasource_is_denied(tmp_path):
    code = f"d = np.DataSource({str(tmp_path)!r})\n{FIG}"
    ok, _, message = SimpleCodeExecutor().execute_code(code, _frame())
    assert not ok
    assert "DataSource" in message


def test_fig_to_image_is_denied():
    """``to_image`` spawns a kaleido subprocess."""
    code = f"{FIG}\nblob = fig.to_image(format='png')"
    ok, _, message = SimpleCodeExecutor().execute_code(code, _frame())
    assert not ok
    assert "to_image" in message


def test_polars_sqlcontext_is_denied():
    code = f"ctx = pl.SQLContext(register_globals=True)\n{FIG}"
    ok, _, message = SimpleCodeExecutor().execute_code(code, _frame())
    assert not ok
    assert "SQLContext" in message


def test_polars_sql_is_denied():
    code = f"r = pl.sql('SELECT 1')\n{FIG}"
    ok, _, message = SimpleCodeExecutor().execute_code(code, _frame())
    assert not ok
    assert "sql" in message


def test_pd_eval_is_denied():
    code = f"pd.eval('1 + 1')\n{FIG}"
    ok, _, message = SimpleCodeExecutor().execute_code(code, _frame())
    assert not ok
    assert "eval" in message


def test_df_query_rce_is_denied(tmp_path):
    """``df.query('@pd.io.common.os.system(...)')`` was a working RCE.

    pandas resolves an ``@name`` from the caller frame, which includes the
    sandbox globals, so ``@pd`` reached the filesystem and a shell.
    """
    sentinel = str(tmp_path / "pwned")
    code = "df.to_pandas().query(\"@pd.io.common.os.system('touch " + sentinel + "')\")\n" + FIG
    ok, _, _ = SimpleCodeExecutor().execute_code(code, _frame())
    assert not ok
    assert not os.path.exists(sentinel)


# --- legitimate figures still run -------------------------------------------


@pytest.mark.parametrize(
    "code",
    [
        # The frame → Plotly handoffs that must survive the denylist.
        "fig = px.scatter(df.to_pandas(), x='x', y='y', color='variety')",
        "vals = df['x'].to_list()\nfig = px.scatter(df.to_pandas(), x='x', y='y', title=str(vals))",
        "rows = df.to_dicts()\nfig = px.scatter(df.to_pandas(), x='x', y='y', title=str(len(rows)))",
        # polars aggregation into a bar.
        "df_modified = df.group_by('variety').agg(pl.col('x').mean())\n"
        "fig = px.bar(df_modified.to_pandas(), x='variety', y='x')",
        # pandas aggregation into a bar.
        "df_modified = df.to_pandas().groupby('variety')['x'].sum().reset_index()\n"
        "fig = px.bar(df_modified, x='variety', y='x')",
        # Post-figure customisation and a reference line sized to the data.
        "limit = max(1, int(df['x'].max()))\n"
        "fig = px.scatter(df.to_pandas(), x='x', y='y')\n"
        "fig.add_shape(type='line', x0=0, y0=0, x1=limit, y1=limit)",
        "fig = px.scatter(df.to_pandas(), x='x', y='y')\nfig.update_layout(showlegend=False)",
    ],
)
def test_legitimate_code_still_runs(code):
    ok, fig, message = SimpleCodeExecutor().execute_code(code, _frame())
    assert ok, message
    assert fig is not None


def test_px_colors_palette_submodule_is_allowed():
    """``px.colors`` and its submodules stay reachable for custom palettes."""
    code = (
        "pal = px.colors.qualitative.Plotly\n"
        "fig = px.scatter(df.to_pandas(), x='x', y='y', color='variety', "
        "color_discrete_sequence=pal)"
    )
    ok, fig, message = SimpleCodeExecutor().execute_code(code, _frame())
    assert ok, message
    assert fig is not None


def test_np_random_is_allowed():
    """``np.random`` is on the module allowlist (``default_rng`` etc.)."""
    code = (
        "rng = np.random.default_rng(0)\n"
        "jitter = rng.normal(0, 1, 3)\n"
        "fig = px.scatter(df.to_pandas(), x='x', y='y', title=str(jitter.shape))"
    )
    ok, fig, message = SimpleCodeExecutor().execute_code(code, _frame())
    assert ok, message
    assert fig is not None


def test_np_function_global_still_computes():
    """A module global that resolves to a function, not a module, is fine."""
    code = "m = np.log10(100.0)\nfig = px.scatter(df.to_pandas(), x='x', y='y', title=str(m))"
    ok, fig, message = SimpleCodeExecutor().execute_code(code, _frame())
    assert ok, message
    assert fig is not None


# --- second layer: the sys.audit hook ---------------------------------------
#
# The name denylist is the first layer; this hook is the backstop that catches
# any Python-level file write, outside-the-install read, process start, socket,
# shared-library load or filesystem mutation that slips past a name check. It is
# armed only while the ``_IN_CODE_FIGURE`` context flag is set (around the exec
# of user code), so these tests set the flag directly to exercise it, always
# clearing it in a finally.


@contextmanager
def _armed():
    from depictio.api.v1.services.figure import code_executor as ce

    token = ce._IN_CODE_FIGURE.set(True)
    try:
        yield
    finally:
        ce._IN_CODE_FIGURE.reset(token)


def test_hook_blocks_file_write_when_armed(tmp_path):
    out = str(tmp_path / "w.txt")
    with _armed():
        with pytest.raises(PermissionError):
            open(out, "w")
    assert not os.path.exists(out)


def test_hook_blocks_read_outside_the_install_when_armed(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("x")
    with _armed():
        with pytest.raises(PermissionError):
            open(str(secret), "r")


def test_hook_allows_reading_package_data_when_armed():
    """Lazy package-data reads inside the Python install must keep working."""
    # os.__file__ lives under the Python installation (base prefix / stdlib).
    with _armed():
        with open(os.__file__, "r") as fh:
            fh.read(1)


def test_hook_blocks_process_start_when_armed():
    import os as _os

    with _armed():
        with pytest.raises(PermissionError):
            _os.system("true")


def test_hook_blocks_socket_when_armed():
    import socket

    with _armed():
        with pytest.raises(PermissionError):
            socket.getaddrinfo("example.com", 80)


def test_hook_blocks_fresh_import_when_armed():
    """A library coaxed into importing a not-yet-loaded package is refused.

    Uses the builtin ``__import__`` — the path a lazy ``import X`` statement in
    library code takes, which is what raises the ``import`` audit event.
    """
    import importlib.util
    import sys

    candidates = ["ftplib", "imaplib", "smtplib", "wave", "mailbox"]
    name = next(
        (c for c in candidates if c not in sys.modules and importlib.util.find_spec(c)),
        None,
    )
    assert name is not None, "no unloaded stdlib module available to probe"
    with _armed():
        with pytest.raises(PermissionError):
            __import__(name)


def test_hook_is_inert_when_not_armed(tmp_path):
    out = str(tmp_path / "ok.txt")
    # No flag set: the hook must do nothing, so ordinary IO works.
    with open(out, "w") as fh:
        fh.write("ok")
    assert open(out).read() == "ok"


def test_flag_is_cleared_after_success():
    from depictio.api.v1.services.figure import code_executor as ce

    ok, _, _ = SimpleCodeExecutor().execute_code(FIG, _frame())
    assert ok
    assert ce._IN_CODE_FIGURE.get() is False


def test_flag_is_cleared_after_failure():
    from depictio.api.v1.services.figure import code_executor as ce

    # Unknown column → the figure exec raises; the flag must still be reset.
    ok, _, _ = SimpleCodeExecutor().execute_code(
        "fig = px.scatter(df.to_pandas(), x='nope', y='nope')", _frame()
    )
    assert not ok
    assert ce._IN_CODE_FIGURE.get() is False
