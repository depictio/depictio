from pydantic import BaseModel, Field

from depictio.models.models.data_collections_types.asset_versions import AssetVersion


class DCGeoJSONConfig(BaseModel):
    """Configuration for GeoJSON data collections.

    GeoJSON DCs store geometry files (FeatureCollection) in S3.
    The feature_id_key maps to Plotly's featureidkey parameter,
    identifying which GeoJSON property matches the locations column.
    """

    feature_id_key: str = "id"

    # Processing metadata (populated during CLI processing)
    #: The *current* generation's location. Kept as the primary field so every
    #: existing reader is untouched; ``versions[-1].s3_location`` is the same
    #: value once a versioned upload has happened.
    s3_location: str | None = None
    file_size_bytes: int | None = None

    #: Upload history, newest last. Empty on every config written before
    #: content-addressed uploads existed, and on any collection that has only
    #: ever been written by an older CLI — which is why nothing may require it.
    versions: list[AssetVersion] = Field(default_factory=list)

    class Config:
        extra = "forbid"
