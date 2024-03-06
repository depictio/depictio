from typing import Dict, List, Optional, Any
import re
from pydantic import (
    BaseModel,
    root_validator,
    validator,
)


class Wildcard(BaseModel):
    name: str
    regex: str
    join_with: Optional[str] = None

    @validator("regex")
    def validate_regex(cls, v):
        try:
            re.compile(v)
            return v
        except re.error:
            raise ValueError("Invalid regex pattern")

    @validator("join_with")
    def validate_join_with(cls, v):
        if v is not None:
            if not isinstance(v, str):
                raise ValueError("join_with must be a string")
        return v


class DCJBrowse2Config(BaseModel):
    index_extension: Optional[str] = None
    regex_wildcards: Optional[List[Wildcard]] = []
    jbrowse_template_location: Optional[str] = None
    jbrowse_config_location: Optional[str] = None


    @root_validator
    def check_wildcards_defined(cls, values):
        files_regex = values.get("files_regex")
        regex_wildcards = values.get("regex_wildcards", [])

        if files_regex:
            wildcards = re.findall(r"\{(\w+)\}", files_regex)
            defined_wildcards = {wc.name for wc in regex_wildcards}

            undefined_wildcards = set(wildcards) - defined_wildcards
            if undefined_wildcards:
                raise ValueError(f"Undefined wildcards in files_regex: {', '.join(undefined_wildcards)}")

        return values

    @validator("format", check_fields=False)
    def validate_format(cls, v, values, **kwargs):
        allowed_values_for_table = ["csv", "tsv", "parquet", "feather", "xls", "xlsx"]
        allowed_values_for_genome_browser = [
            "gff3",
            "gff",
            "gtf",
            "bed",
            "bigbed",
            "vcf",
            "bigwig",
            "bw",
            "bam",
            "cram",
            "bai",
            "crai",
            "fai",
            "tbi",
            "csi",
            "gzi",
            "2bit",
            "sizes",
            "chrom.sizes",
            "chromSizes",
            "fasta",
            "fa",
            "fna",
            "fasta.gz",
        ]

        # Use the 'type' to determine allowed formats
        data_type = values.get("type", "").lower()  # Ensuring type is accessed in lowercase
        if data_type:  # Check if 'type' is available
            allowed_values = {"table": allowed_values_for_table, "genome browser": allowed_values_for_genome_browser}.get(
                data_type, []
            )  # Default to empty list if type is not recognized

            if v.lower() not in allowed_values:
                allowed_formats_str = ", ".join(allowed_values)
                raise ValueError(f"Invalid format '{v}' for type '{data_type}'. Allowed formats for this type are: {allowed_formats_str}")
        else:
            # Handle case where 'type' is not yet validated or missing
            raise ValueError("Type must be validated before format.")

        return v
