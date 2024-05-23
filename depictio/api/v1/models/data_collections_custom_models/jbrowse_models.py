from typing import Optional
from pydantic import (
    BaseModel,
    validator,
)


class DCJBrowse2Config(BaseModel):
    index_extension: Optional[str] = None
    jbrowse_template_location: Optional[str] = None

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
            allowed_values = {"table": allowed_values_for_table, "jbrowse2": allowed_values_for_genome_browser}.get(
                data_type, []
            )  # Default to empty list if type is not recognized

            if v.lower() not in allowed_values:
                allowed_formats_str = ", ".join(allowed_values)
                raise ValueError(f"Invalid format '{v}' for type '{data_type}'. Allowed formats for this type are: {allowed_formats_str}")
        else:
            # Handle case where 'type' is not yet validated or missing
            raise ValueError("Type must be validated before format.")

        return v
