"""Polars source for the predicates the server applies.

The emitter lives in ``depictio.notebook.predicates``, with the notebook
client, because the exported document runs it too (its funnel stages are
computed from ``depictio_state`` at run time). This module is the server's
name for it.
"""

from depictio.notebook.predicates import (
    CATEGORICAL_TYPES,
    DATE_RANGE_TYPES,
    PredicateSource,
    dtype_source,
    emit_filter_expr,
    emit_predicate,
    literal,
    literal_list,
)

__all__ = [
    "CATEGORICAL_TYPES",
    "DATE_RANGE_TYPES",
    "PredicateSource",
    "dtype_source",
    "emit_filter_expr",
    "emit_predicate",
    "literal",
    "literal_list",
]
