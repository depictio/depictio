from pydantic import BaseModel


class DCGeoJSONConfig(BaseModel):
    """Configuration for GeoJSON data collections.

    GeoJSON DCs store geometry files (FeatureCollection) in S3.
    The feature_id_key maps to Plotly's featureidkey parameter,
    identifying which GeoJSON property matches the locations column.
    """

    feature_id_key: str = "id"

    # Processing metadata (populated during CLI processing)
    s3_location: str | None = None
    file_size_bytes: int | None = None

    class Config:
        extra = "forbid"
