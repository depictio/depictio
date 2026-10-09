"""
Simple and secure code executor using RestrictedPython.

This replaces the complex custom security implementation with RestrictedPython,
which is battle-tested and maintained by the Zope Foundation.
"""

import contextvars
import os
import site
import sys
import traceback
import types
from typing import Any, Dict, Tuple

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import polars as pl
from plotly.basedatatypes import BaseFigure, BasePlotlyType
from RestrictedPython import compile_restricted
from RestrictedPython.Guards import safe_builtins, safe_globals, safer_getattr

from depictio.api.v1.configs.logging_init import logger


def _allowed_module_ids() -> frozenset[int]:
    """Identity set of the modules a code figure may reach through an attribute.

    The module globals (`px`, `pl`, `pd`, `np`, `go`) are whole libraries, so a
    bare attribute walk (`pd.io.common.os`, no underscore in the chain) reaches
    the filesystem and arbitrary code. The guard below denies any attribute that
    *is* a module unless it is one of these — the submodules the repo's own code
    figures, templates and docs legitimately use:

    * ``px.colors`` and its submodules (``qualitative``, ``sequential``,
      ``diverging``, ``cyclical`` and the rest) — palettes;
    * ``np.random`` — ``np.random.default_rng`` and friends.

    Nothing else: no deep chain off a module global appears in any code figure
    in the tree, so allowing more would only widen the reach for no caller.
    """
    allowed: set[int] = set()

    def _add_tree(mod: types.ModuleType) -> None:
        if id(mod) in allowed:
            return
        allowed.add(id(mod))
        for attr in dir(mod):
            try:
                child = getattr(mod, attr)
            except Exception:
                continue
            if isinstance(child, types.ModuleType):
                _add_tree(child)

    # px.colors is a small, self-contained palette package — safe to walk whole.
    _add_tree(px.colors)
    # np.random is allowed as a leaf: default_rng etc. are functions, not modules.
    allowed.add(id(np.random))
    return frozenset(allowed)


# Built once at import; the module objects are process-stable.
_ALLOWED_MODULE_IDS = _allowed_module_ids()

# I/O and escape names denied on ANY object. This is the FIRST of two layers:
# it is the only one that reaches polars/numpy I/O, whose work happens in Rust/C
# and never raises a Python ``sys.audit`` event the hook below could see. The
# prefixes cover the polars/pandas reader/writer families (`read_csv`,
# `scan_parquet`, `write_delta`, `sink_ipc`); the explicit set covers the pandas
# `to_*` serializers, numpy load/save/dump, the (de)serialize + Config file I/O,
# the Excel/HDF writer classes, the pandas-expression RCE surfaces (`eval` /
# `query`), the polars SQL surfaces, the dynamic-execution builtins and the
# Plotly figure writers. `to_dict` / `to_list` / `to_numpy` / `to_pandas` are
# deliberately NOT here — code figures rely on them to hand a frame to Plotly
# Express. None of the names below appears in any code figure in the repo.
_DENY_NAME_PREFIXES = ("read_", "scan_", "write_", "sink_")
_DENY_NAMES = frozenset(
    {
        # pandas / polars serializers
        "to_csv",
        "to_parquet",
        "to_pickle",
        "to_json",
        "to_excel",
        "to_hdf",
        "to_sql",
        "to_feather",
        "to_stata",
        "to_clipboard",
        "to_orc",
        "to_xml",
        "to_html",
        "to_latex",
        "to_markdown",
        "to_ipc",
        "to_avro",
        "to_delta",
        "to_string",  # pandas: to_string(buf=path) writes a file
        # polars frame (de)serialization (Rust I/O) and Config file I/O
        "serialize",
        "deserialize",
        "save_to_file",
        "load_from_file",
        # pandas file-handle classes (open a writable/readable path on construct)
        "ExcelWriter",
        "ExcelFile",
        "HDFStore",
        # pandas global IO config / expression evaluation (RCE via @-locals)
        "set_option",
        "eval",
        "query",
        # polars SQL (register_globals exposes the sandbox namespace)
        "sql",
        "SQLContext",
        "register_globals",
        # numpy persistence
        "load",
        "loads",
        "save",
        "savez",
        "savez_compressed",
        "savetxt",
        "loadtxt",
        "genfromtxt",
        "fromfile",
        "tofile",
        "memmap",
        "fromregex",
        "dump",  # ndarray.dump(path)
        "dumps",  # ndarray.dumps()
        "DataSource",  # numpy: opens paths / URLs
        # process / dynamic execution / import
        "open",
        "system",
        "popen",
        "import_module",
        "exec",
        "compile",
        # Plotly writers / renderers (also caught by the write_ prefix, pinned
        # here so the intent is explicit); to_image spawns a kaleido process
        "show",
        "write_image",
        "write_html",
        "write_json",
        "to_image",
    }
)


def safe_getitem(obj, key):
    """Safe getitem for pandas DataFrame and Series operations."""
    return obj[key]


def safe_getattr(obj, name, default=None, getattr=getattr):
    """Guarded getattr for code figures.

    Built on RestrictedPython's ``safer_getattr`` — which keeps the underscore
    rule, the ``str.format`` / ``string.Formatter`` escape block and the frame
    introspection block — then adds two Depictio rules so a figure that only
    needs to read ``df`` and build a Plotly chart cannot read or write server
    files or reach arbitrary code:

    * **name rule** — an I/O or dynamic-execution name (``read_*`` / ``scan_*`` /
      ``write_*`` / ``sink_*`` prefixes, or one of ``_DENY_NAMES``) is refused on
      any object, before the attribute is even fetched;
    * **module rule** — an attribute whose value is a module is refused unless it
      is on ``_ALLOWED_MODULE_IDS``, which stops ``pd.io.common.os`` and every
      other walk off a module global.
    """
    if isinstance(name, str):
        if name in _DENY_NAMES or name.startswith(_DENY_NAME_PREFIXES):
            raise AttributeError(f'access to "{name}" is not allowed in a code figure')
    value = safer_getattr(obj, name, default)
    if isinstance(value, types.ModuleType) and id(value) not in _ALLOWED_MODULE_IDS:
        mod_name = getattr(value, "__name__", name)
        raise AttributeError(f'access to module "{mod_name}" is not allowed in a code figure')
    return value


_EMPTY_FRAME = pd.DataFrame()
# What a figure writes into: the containers and frames it builds, the pandas
# indexers behind `df.loc[mask, "col"] = v`, and plotly figures and their parts.
_WRITABLE: tuple[type, ...] = (
    dict,
    list,
    set,
    np.ndarray,
    pd.DataFrame,
    pd.Series,
    type(_EMPTY_FRAME.loc),
    type(_EMPTY_FRAME.iloc),
    type(_EMPTY_FRAME.at),
    type(_EMPTY_FRAME.iat),
    BaseFigure,
    BasePlotlyType,
)


def safe_write(obj):
    """The object a subscript or attribute write lands on, if a figure may write to it.

    RestrictedPython compiles ``obj[key] = value`` and ``obj.attr = value`` to a
    write on ``_write_(obj)``, so the guard takes the object alone and returns
    the target of the write. A figure can fill a labels dict, add a pandas
    column or set a layout field. Anything else is refused: the modules and
    classes in the globals (``px``, ``pl.DataFrame``...) are shared by every
    render in the process, and a write there would patch them for the next one.
    """
    if isinstance(obj, _WRITABLE):
        return obj
    raise TypeError(f"A code figure cannot write to a {type(obj).__name__} object")


def safe_setattr(obj, name, value, setattr=setattr):
    """Safe setattr that allows pandas operations."""
    setattr(obj, name, value)
    return value


def safe_iter_unpack_sequence(seq, *args):
    """Safe implementation of _iter_unpack_sequence_ for RestrictedPython."""
    # RestrictedPython may pass additional arguments, so we accept them but only use seq
    return iter(seq)


def safe_unpack_sequence(seq, expected, *args):
    """Safe implementation of _unpack_sequence_ for RestrictedPython.

    Emitted for a plain tuple-unpack assignment (``a, b = ...``), which
    ``_iter_unpack_sequence_`` — the for-loop target hook — does not cover.
    Materialising the sequence reaches nothing that indexing it one element at
    a time could not.
    """
    return list(seq)


def safe_getiter(obj):
    """Safe implementation of _getiter_ for RestrictedPython."""
    return iter(obj)


# ---------------------------------------------------------------------------
# Second layer: a process-wide ``sys.audit`` hook.
#
# The name denylist above is the first layer, but a denylist alone leaks: a new
# writer/reader name, a file-handle class, or an expression surface that resolves
# a payload from the sandbox namespace all slip past it. This hook is the
# backstop. It is installed once at import and does nothing unless the
# ``_IN_CODE_FIGURE`` context flag is set — which only ``execute_code`` sets,
# around the ``exec`` of user code. So it costs one flag read per audit event in
# normal operation and enforces only while a figure's code is running.
#
# It cannot see polars/numpy Rust/C I/O (that work never raises a Python audit
# event), which is exactly why the name denylist stays the first line of
# defence. What it does catch is every Python-level attempt to open a file for
# writing, read a file outside the Python install, start a process, open a
# socket, load a shared library, mutate the filesystem, or import a package that
# was not already loaded.
# ---------------------------------------------------------------------------

_IN_CODE_FIGURE: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "depictio_in_code_figure", default=False
)


def _read_ok_prefixes() -> tuple[str, ...]:
    """Directories a code figure may read from: the Python installation only.

    Plotly and pandas lazily read their own package data (templates, colour
    scales, timezone tables) from site-packages and the stdlib on first use, so
    those reads must keep working. Everything else — the server's data files,
    the user's home, ``/etc`` — is off limits. Paths are normalised absolute
    (not realpath: resolving symlinks would itself hit the filesystem and could
    raise audit events inside the hook).
    """
    prefixes: set[str] = set()
    for base in (sys.prefix, sys.base_prefix, sys.exec_prefix, sys.base_exec_prefix):
        if base:
            prefixes.add(os.path.normpath(os.path.abspath(base)))
    for getter in (
        getattr(site, "getsitepackages", None),
        getattr(site, "getusersitepackages", None),
    ):
        if getter is None:
            continue
        try:
            result = getter()
        except Exception:
            continue
        paths = result if isinstance(result, (list, tuple)) else [result]
        for p in paths:
            if p:
                prefixes.add(os.path.normpath(os.path.abspath(p)))
    return tuple(prefixes)


_READ_OK_PREFIXES = _read_ok_prefixes()

# Write-access bits for the ``os.open`` form of the ``open`` audit event, where
# ``mode`` is None and the integer ``flags`` carry the intent.
_WRITE_OPEN_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC

# Audit events refused outright while a code figure runs.
_BLOCKED_AUDIT_EVENTS = frozenset(
    {
        # process creation
        "os.system",
        "os.exec",
        "os.spawn",
        "os.posix_spawn",
        "os.startfile",
        "os.fork",
        "os.forkpty",
        "pty.spawn",
        "subprocess.Popen",
        # network
        "socket.connect",
        "socket.getaddrinfo",
        "socket.gethostbyname",
        "socket.sethostname",
        "urllib.Request",
        # shared libraries
        "ctypes.dlopen",
        "ctypes.LoadLibrary",
        # filesystem mutation (shutil routes through these os.* events)
        "os.remove",
        "os.rename",
        "os.replace",
        "os.unlink",
        "os.mkdir",
        "os.rmdir",
        "os.chmod",
        "os.chown",
        "os.symlink",
        "os.link",
        "os.truncate",
        "shutil.copyfile",
        "shutil.copymode",
        "shutil.copystat",
        "shutil.rmtree",
        "shutil.move",
    }
)


def _audit_open(path, mode, flags) -> None:
    """Allow a read inside the Python install; refuse writes and outside reads."""
    # A bare file-descriptor target is an already-open handle — nothing to vet.
    if isinstance(path, int) or path is None:
        return
    if isinstance(path, bytes):
        try:
            path = path.decode()
        except Exception:
            raise PermissionError("opening this path is not allowed in a code figure")
    if not isinstance(path, str):
        return

    if isinstance(mode, str):
        is_write = any(c in mode for c in "waxWAX+")
    elif isinstance(flags, int):
        is_write = bool(flags & _WRITE_OPEN_FLAGS)
    else:
        # Unknown shape — fail closed.
        is_write = True
    if is_write:
        raise PermissionError("writing files is not allowed in a code figure")

    resolved = os.path.normpath(os.path.abspath(path))
    if not any(resolved == pre or resolved.startswith(pre + os.sep) for pre in _READ_OK_PREFIXES):
        raise PermissionError(
            "reading files outside the Python installation is not allowed in a code figure"
        )


def _code_figure_audit_hook(event: str, args) -> None:
    """Enforce the sandbox boundary while — and only while — a figure runs."""
    if not _IN_CODE_FIGURE.get():
        return
    if event == "open":
        _audit_open(
            args[0] if args else None,
            args[1] if len(args) > 1 else None,
            args[2] if len(args) > 2 else None,
        )
        return
    if event in _BLOCKED_AUDIT_EVENTS:
        raise PermissionError(f"operation '{event}' is not allowed in a code figure")
    if event == "import":
        name = args[0] if args else ""
        top = (name or "").split(".")[0]
        # The plotting stack is fully imported at module load, so every lazy
        # import it makes resolves to a top-level already in ``sys.modules`` and
        # is allowed. A top-level that is NOT yet loaded is a package the figure
        # is trying to pull in fresh (e.g. ``pty``, ``ctypes.util``) — refused.
        # (User code cannot ``import`` at all: RestrictedPython has no
        # ``__import__``. This guards a library being coaxed into a new import.)
        if top and top not in sys.modules:
            raise PermissionError(f"importing '{name}' is not allowed in a code figure")


_AUDIT_HOOK_INSTALLED = False


def _install_audit_hook_once() -> None:
    """Install the audit hook a single time per process (hooks can't be removed)."""
    global _AUDIT_HOOK_INSTALLED
    if not _AUDIT_HOOK_INSTALLED:
        sys.addaudithook(_code_figure_audit_hook)
        _AUDIT_HOOK_INSTALLED = True


_install_audit_hook_once()


class SimpleCodeExecutor:
    """
    Simplified secure code executor using RestrictedPython.

    Provides a much cleaner and more maintainable approach than custom AST parsing.
    """

    def __init__(self):
        """Initialize the executor with safe execution environment."""
        # Create safe execution environment
        self.safe_globals = {
            **safe_globals,
            # Visualization libraries only - no data import/export
            "px": px,
            # Note: go (plotly.graph_objects) available for code mode
            "go": go,
            # Polars & Pandas
            "pl": pl,
            "pd": pd,
            "np": np,
            # Safe builtins
            "__builtins__": safe_builtins,
            # Guards for dataframe operations
            "_getitem_": safe_getitem,
            "_getattr_": safe_getattr,
            "_write_": safe_write,
            "_setattr_": safe_setattr,
            # Additional safe functions for complex operations
            "_iter_unpack_sequence_": safe_iter_unpack_sequence,
            "_unpack_sequence_": safe_unpack_sequence,
            "_getiter_": safe_getiter,
            # RestrictedPython's hook for `f(*args, **kwargs)` unpacking, which
            # a code figure needs to spread `**depictio_group_kwargs`. Plain
            # forwarding is the safe default: it reaches nothing the same call
            # with explicit keywords could not already reach.
            "_apply_": lambda func, *args, **kwargs: func(*args, **kwargs),
            "enumerate": enumerate,
            "zip": zip,
            "len": len,
            "range": range,
            "list": list,
            "dict": dict,
            "tuple": tuple,
            # RestrictedPython's `safe_builtins` ships `abs`, `round`, `sorted`
            # and the numeric constructors but not these, which reads as an
            # oversight rather than a boundary: they are pure, take no handle
            # on anything, and are the obvious way to size an axis or a
            # reference line. Their absence surfaces only at render time, as a
            # bare `NameError` in the middle of a figure.
            "max": max,
            "min": min,
            "sum": sum,
            "any": any,
            "all": all,
            "set": set,
            "reversed": reversed,
        }

    def _validate_no_df_assignment(self, code: str) -> Tuple[bool, str]:
        """
        Validate that the code doesn't attempt to reassign the 'df' variable.

        Args:
            code: Python code to validate

        Returns:
            (is_valid: bool, error_message: str)
        """
        import ast

        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return False, f"Syntax error in code: {e}"

        # Check for df assignment
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "df":
                        return False, "❌ Cannot reassign 'df' variable. Use the provided dataset."
            elif isinstance(node, ast.AugAssign):
                if isinstance(node.target, ast.Name) and node.target.id == "df":
                    return (
                        False,
                        "❌ Cannot modify 'df' variable assignment. Use the provided dataset.",
                    )

        return True, ""

    def execute_code(
        self,
        code: str,
        dataframe: pl.DataFrame,
        extra_globals: Dict[str, Any] | None = None,
    ) -> Tuple[bool, Any, str]:
        """
        Execute user code safely using RestrictedPython with df_modified constraint support.

        Args:
            code: Python code to execute
            dataframe: DataFrame to make available as 'df'
            extra_globals: Additional names bound in the sandbox, alongside
                `df` and the plotting libraries (e.g. `depictio_group_kwargs`).

        Returns:
            (success: bool, result: Any, message: str)
        """
        from depictio.api.v1.services.figure.code_mode import analyze_constrained_code

        # Analyze code structure first
        analysis = analyze_constrained_code(code)

        if not analysis["is_valid"]:
            return False, None, f"❌ Code validation failed: {analysis['error_message']}"
        try:
            # First, validate that df is not being reassigned
            is_valid, validation_error = self._validate_no_df_assignment(code)
            if not is_valid:
                return False, None, validation_error

            # Prepare execution environment
            execution_globals = self.safe_globals.copy()
            execution_globals["df"] = dataframe.clone()  # Provide DataFrame copy
            # Server-provided names come last so a collision in safe_globals
            # cannot shadow them. Plain data only (dicts, strings): nothing
            # here widens what the sandbox can reach.
            execution_globals.update(extra_globals or {})
            execution_locals: Dict[str, Any] = {}

            # Handle preprocessing if needed
            if analysis["has_preprocessing"]:
                # Compile and execute preprocessing code
                preprocessing_code = analysis["preprocessing_code"]
                preprocessing_bytecode = compile_restricted(
                    preprocessing_code, filename="<preprocessing>", mode="exec"
                )

                if preprocessing_bytecode is None:
                    return (
                        False,
                        None,
                        "❌ Preprocessing compilation failed - likely contains restricted operations",
                    )

                # Execute preprocessing — the audit hook is armed only for the
                # duration of this exec, then disarmed in the finally (so the
                # except handler's traceback formatting, which reads source
                # files, is never caught by it).
                _token = _IN_CODE_FIGURE.set(True)
                try:
                    exec(preprocessing_bytecode, execution_globals, execution_locals)
                finally:
                    _IN_CODE_FIGURE.reset(_token)

                # Verify the preprocessing actually produced something. The
                # check used to demand a name starting with "df", which is a
                # convention, not a requirement: code whose intermediates were
                # called anything else was rejected here even though it ran.
                if not execution_locals:
                    return (
                        False,
                        None,
                        "❌ Preprocessing failed: no variables were created",
                    )

            # Execute figure generation code
            figure_code = analysis["figure_code"]
            figure_bytecode = compile_restricted(figure_code, filename="<figure_code>", mode="exec")

            if figure_bytecode is None:
                return (
                    False,
                    None,
                    "❌ Figure code compilation failed - likely contains restricted operations",
                )

            # Execute figure generation (execution_locals already contains
            # df_modified if created). Audit hook armed for this exec only.
            _token = _IN_CODE_FIGURE.set(True)
            try:
                exec(figure_bytecode, execution_globals, execution_locals)
            finally:
                _IN_CODE_FIGURE.reset(_token)

            # Look for the figure result
            fig = execution_locals.get("fig")
            if fig is None:
                return False, None, "❌ No figure found. Please create a variable named 'fig'."

            # Basic validation that it's a Plotly figure
            if not hasattr(fig, "to_dict"):
                return False, None, "❌ The 'fig' variable is not a valid Plotly figure."

            preprocessing_msg = " with preprocessing" if analysis["has_preprocessing"] else ""
            return True, fig, f"✅ Code executed successfully{preprocessing_msg}!"

        except SyntaxError as e:
            # Handle syntax errors separately with clearer messaging
            error_msg = f"❌ Python Syntax Error: {e.msg}"
            if hasattr(e, "text") and e.text:
                error_msg += f"\nProblem line: {e.text.strip()}"
            if hasattr(e, "offset") and e.offset:
                error_msg += f"\n{' ' * (e.offset - 1)}^"
            logger.warning(f"Code syntax error: {error_msg}")
            return False, None, error_msg
        except Exception as e:
            error_msg = f"Execution error: {str(e)}"
            logger.warning(f"Code execution failed: {error_msg}")
            # Include traceback for debugging (but not full system info)
            tb_lines = traceback.format_exc().split("\n")
            # Only include the last few lines to avoid exposing system details
            safe_tb = "\n".join(tb_lines[-3:])
            return False, None, f"{error_msg}\n{safe_tb}"

    def execute_preprocessing_only(
        self, code: str, dataframe: pl.DataFrame
    ) -> Tuple[bool, Any, str]:
        """
        Execute only preprocessing code and return df_modified.

        Args:
            code: Full user code (will extract preprocessing part)
            dataframe: DataFrame to make available as 'df'

        Returns:
            (success: bool, df_modified: DataFrame, message: str)
        """
        from depictio.api.v1.services.figure.code_mode import analyze_constrained_code

        # Analyze code structure first
        analysis = analyze_constrained_code(code)

        if not analysis["is_valid"]:
            return False, None, f"❌ Code validation failed: {analysis['error_message']}"

        if not analysis["has_preprocessing"]:
            return False, None, "❌ No preprocessing code found"

        try:
            # Prepare execution environment
            execution_globals = self.safe_globals.copy()
            execution_globals["df"] = dataframe.clone()  # Provide DataFrame copy
            execution_locals: Dict[str, Any] = {}

            # Compile and execute preprocessing code only
            preprocessing_code = analysis["preprocessing_code"]
            preprocessing_bytecode = compile_restricted(
                preprocessing_code, filename="<preprocessing>", mode="exec"
            )

            if preprocessing_bytecode is None:
                return (
                    False,
                    None,
                    "❌ Preprocessing compilation failed - likely contains restricted operations",
                )

            # Execute preprocessing — audit hook armed for this exec only.
            _token = _IN_CODE_FIGURE.set(True)
            try:
                exec(preprocessing_bytecode, execution_globals, execution_locals)
            finally:
                _IN_CODE_FIGURE.reset(_token)

            # Verify df_modified was created
            if "df_modified" not in execution_locals:
                return False, None, "❌ Preprocessing failed: 'df_modified' variable not created"

            df_modified = execution_locals["df_modified"]

            # Verify that df_modified is a Polars DataFrame
            if not isinstance(df_modified, pl.DataFrame):
                return (
                    False,
                    None,
                    f"❌ Expected Polars DataFrame, got {type(df_modified)}: {df_modified}",
                )
            logger.info("df_modified is already a Polars DataFrame")
            logger.info(f"df_modified head:\n{df_modified.head()}")
            return True, df_modified, "✅ Preprocessing successful"

        except Exception as e:
            error_msg = f"Preprocessing execution error: {str(e)}"
            logger.warning(f"Preprocessing execution failed: {error_msg}")
            return False, None, error_msg


def get_code_examples() -> Dict[str, str]:
    """Get predefined code examples for different plot types using iris dataset."""
    return {
        "Scatter Plot": """# Basic scatter plot
fig = px.scatter(df, x='sepal.length', y='sepal.width', color='variety', title='Sepal Dimensions')""",
        "Histogram": """# Histogram
fig = px.histogram(df, x='petal.length', color='variety', title='Petal Length Distribution')""",
        "Box Plot": """# Box plot
fig = px.box(df, x='variety', y='petal.width', title='Petal Width by Variety')""",
        "Pie Chart": """# Pie chart with groupby
df_modified = df.to_pandas().groupby('variety')['sepal.length'].sum().reset_index()
fig = px.pie(df_modified, values='sepal.length', names='variety', title='Sepal Length Distribution by Variety')""",
        "Pandas Processing": """# Data processing with pandas
df_modified = df.to_pandas().groupby('variety')['sepal.width'].mean().reset_index()
fig = px.bar(df_modified, x='variety', y='sepal.width', color='variety', title='Average Sepal Width by Variety')""",
        "Polars Processing": """# Data processing with polars
df_modified = df.group_by('variety').agg(pl.col('petal.length').mean())
fig = px.bar(df_modified, x='variety', y='petal.length', color='variety', title='Average Petal Length by Variety')""",
        "Custom Styling": """# Custom styled plot
fig = px.scatter(df, x='sepal.length', y='petal.length', color='variety', size='sepal.width', hover_data=['petal.width'])
fig.update_layout(title='Sepal vs Petal Length', xaxis_title='Sepal Length (cm)', yaxis_title='Petal Length (cm)')""",
    }
