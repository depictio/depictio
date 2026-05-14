from pydantic import model_validator

from depictio.models.models.data_collections_types.table import DCTableConfig


class DCTableCoordinatesConfig(DCTableConfig):
    """Table DC variant carrying explicit lat/lon column hints for Map components.

    Same dc_type ("table") as DCTableConfig — this is a programmatic specialisation
    materialised at deserialisation time when the persisted config dict carries
    `lat_column` / `lon_column` keys. All table-format handling (CSV/TSV/Parquet,
    polars_kwargs, keep_columns, columns_description) is inherited unchanged.
    """

    lat_column: str
    lon_column: str
    crs: str = "EPSG:4326"

    @model_validator(mode="after")
    def _lat_lon_distinct(self) -> "DCTableCoordinatesConfig":
        if self.lat_column == self.lon_column:
            raise ValueError("lat_column and lon_column must differ")
        return self
