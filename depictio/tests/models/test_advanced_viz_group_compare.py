"""The `group_compare` kind's model contract.

What a dashboard may write into the component, and what the renderer may
therefore rely on reading back. `test_advanced_viz_config_alignment.py` already
checks that the renderer reads no key the model lacks; this pins the other
direction, the values and the registry entries the kind cannot work without.
"""

from __future__ import annotations

from typing import get_args

import pytest
from pydantic import TypeAdapter, ValidationError

from depictio.models.components.advanced_viz.configs import GroupCompareConfig, VizConfig
from depictio.models.components.advanced_viz.sampling import KIND_SAMPLING_POLICY
from depictio.models.components.advanced_viz.schemas import (
    CANONICAL_SCHEMAS,
    KIND_METADATA,
    ROLE_NAMES,
)
from depictio.models.components.types import AdvancedVizKind

KIND = "group_compare"
VIZ_CONFIG = TypeAdapter(VizConfig)


def test_the_kind_is_registered_everywhere_the_pipeline_looks():
    assert KIND in get_args(AdvancedVizKind)
    assert KIND in CANONICAL_SCHEMAS
    assert KIND in ROLE_NAMES
    assert KIND in KIND_METADATA
    # A missing sampling policy raises at request time, not at import time.
    assert KIND_SAMPLING_POLICY[KIND] == "none"


def test_the_only_required_role_is_the_row_id():
    """The features are inferred from the schema, like complex_heatmap's matrix.

    Naming them would mean listing 2000 gene columns in a dashboard YAML.
    """
    assert set(CANONICAL_SCHEMAS[KIND]) == {"index"}


def test_the_kind_resolves_through_the_discriminated_union():
    config = VIZ_CONFIG.validate_python({"viz_kind": KIND, "index_col": "cell_id"})
    assert isinstance(config, GroupCompareConfig)
    assert config.index_col == "cell_id"


def test_the_defaults_are_the_ones_the_renderer_falls_back_to():
    """Drift here silently changes what an unconfigured component computes."""
    config = GroupCompareConfig()
    assert config.index_col == "index"
    assert config.group_col is None
    assert config.test == "wilcoxon"
    assert config.log_transform is True
    assert config.max_features == 2000
    assert config.min_observations == 3
    assert config.fdr_threshold == 0.05
    assert config.log2fc_threshold == 1.0
    assert config.top_n_labels == 20


@pytest.mark.parametrize(
    "patch",
    [
        {"test": "anova"},
        {"fdr_threshold": 0},
        {"fdr_threshold": 1},
        {"log2fc_threshold": -1},
        {"min_observations": 1},
        {"max_features": 5},
        {"max_features": 20_001},
        {"top_n_labels": -1},
        # extra="forbid": a key with no field makes the whole component
        # unloadable, which is why the alignment test exists at all.
        {"pseudocount": 1.0},
    ],
)
def test_out_of_contract_settings_are_refused(patch: dict):
    with pytest.raises(ValidationError):
        GroupCompareConfig(**patch)


def test_the_label_column_is_optional_and_the_groups_are_not_bound_columns():
    """The two groups are resolved at compute time, never declared here.

    A saved lasso exists in one reader's browser; a component that named it
    would be a component that only works for one person.
    """
    fields = set(GroupCompareConfig.model_fields)
    assert not {f for f in fields if f.startswith("group_a") or f.startswith("group_b")}
    assert GroupCompareConfig(group_col="cluster").group_col == "cluster"
