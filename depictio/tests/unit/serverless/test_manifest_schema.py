"""Pin the serverless bundle-manifest contract.

Two guards:

1. The committed JSON-schema snapshot (``serverless.schema.json``) must match
   what the Pydantic model generates — any model change forces a deliberate
   snapshot regeneration, which is the reviewable event for a contract change
   (the TypeScript mirror in ``packages/depictio-static-core`` pins against the
   same snapshot).
2. The hand-written fixture manifest used by the static runtime's tests
   (``packages/depictio-static-core/fixtures/manifest-basic.json``) must
   validate against the model — the cross-language fixture and the Python
   contract cannot drift apart silently.

Regenerate the snapshot after an intentional model change with:

    uv run python -c "import json; from depictio.models.models.serverless import \
BundleManifest; open('depictio/models/models/serverless.schema.json','w').write(\
json.dumps(BundleManifest.model_json_schema(), indent=2, sort_keys=True) + '\\n')"
"""

import json
from pathlib import Path

from depictio.models.models.serverless import (
    MANIFEST_VERSION,
    BundleManifest,
    BundleMode,
    ComponentTier,
    Producer,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
SCHEMA_PATH = REPO_ROOT / "depictio" / "models" / "models" / "serverless.schema.json"
FIXTURE_PATH = REPO_ROOT / "packages" / "depictio-static-core" / "fixtures" / "manifest-basic.json"


def test_schema_snapshot_matches_model():
    committed = json.loads(SCHEMA_PATH.read_text())
    generated = BundleManifest.model_json_schema()
    assert generated == committed, (
        "BundleManifest changed but depictio/models/models/serverless.schema.json was not "
        "regenerated — this snapshot is the contract shared with "
        "packages/depictio-static-core; regenerate it deliberately (see module docstring)."
    )


def test_fixture_manifest_validates():
    manifest = BundleManifest.model_validate_json(FIXTURE_PATH.read_text())
    assert manifest.manifest_version == MANIFEST_VERSION
    assert manifest.mode is BundleMode.SINGLE_FILE
    assert manifest.producer is Producer.BUILD_FROM_SPEC
    # The runtime relies on a non-empty dashboard id (ComponentRenderer silently
    # no-ops figure/table/image/map/jbrowse/multiqc without one).
    assert manifest.dashboard.id
    # Every non-live component must carry a frozen payload or an omission reason.
    for component_id, entry in manifest.tiers.items():
        if entry.tier in (ComponentTier.FROZEN, ComponentTier.PARTIAL):
            kind = next(
                (
                    c.get("component_type")
                    for c in manifest.dashboard.doc["stored_metadata"]
                    if c.get("index") == component_id
                ),
                None,
            )
            assert component_id in manifest.frozen or kind == "text", (
                f"{component_id} is {entry.tier} but has no frozen payload"
            )
    # inline: URIs must resolve against inline_blobs in single-file mode.
    for dc_id, ref in manifest.data_refs.items():
        if ref.uri.startswith("inline:"):
            assert ref.uri.removeprefix("inline:") in manifest.inline_blobs, (
                f"data_refs[{dc_id}].uri points at a missing inline blob"
            )


def test_fixture_is_json_serialisable_roundtrip():
    # Mirrors test_payload.py's guard: NaN/Inf tokens would blank the embedded blob.
    manifest = BundleManifest.model_validate_json(FIXTURE_PATH.read_text())
    dumped = manifest.model_dump(mode="json")
    text = json.dumps(dumped)
    assert "NaN" not in text and "Infinity" not in text
    assert BundleManifest.model_validate(json.loads(text)) == manifest
