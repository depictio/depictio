"""Built-in reference assemblies for the genome browser.

Sequences come from the UCSC download server (``.2bit`` + ``chrom.sizes``),
which sends ``Access-Control-Allow-Origin: *`` and honours ``Range``, so the
browser reads them directly: they are public, identical for every user and
far too large to proxy. Each preset also carries UCSC's ``chromAlias`` file,
so tracks named ``1``/``chr1``/``NC_000001.11`` all land on the same sequence,
and one gene annotation bigBed where UCSC publishes one.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

_UCSC = "https://hgdownload.soe.ucsc.edu"


@dataclass(frozen=True)
class AssemblyPreset:
    name: str
    display_name: str
    organism: str
    twobit_uri: str
    chrom_sizes_uri: str
    chrom_alias_uri: str
    aliases: tuple[str, ...] = ()
    annotation_uri: str | None = None
    annotation_name: str = "Genes"
    default_location: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "organism": self.organism,
            "aliases": list(self.aliases),
            "has_annotation": self.annotation_uri is not None,
            "default_location": self.default_location,
        }


def _golden_path(
    db: str,
    display_name: str,
    organism: str,
    aliases: tuple[str, ...],
    annotation: str | None,
    default_location: str,
    annotation_name: str = "Genes",
) -> AssemblyPreset:
    base = f"{_UCSC}/goldenPath/{db}/bigZips/{db}"
    return AssemblyPreset(
        name=db,
        display_name=display_name,
        organism=organism,
        twobit_uri=f"{base}.2bit",
        chrom_sizes_uri=f"{base}.chrom.sizes",
        chrom_alias_uri=f"{base}.chromAlias.txt",
        aliases=aliases,
        annotation_uri=annotation,
        annotation_name=annotation_name,
        default_location=default_location,
    )


def _genark_bb(accession: str, asm_name: str) -> str:
    """NCBI RefSeq genes bigBed of a UCSC GenArk hub (RefSeq sequence names)."""
    _, digits = accession.split("_")
    parts = digits.split(".")[0]
    path = "/".join(parts[i : i + 3] for i in range(0, 9, 3))
    return f"{_UCSC}/hubs/GCF/{path}/{accession}/bbi/{accession}_{asm_name}.ncbiRefSeq.bb"


_PRESETS: tuple[AssemblyPreset, ...] = (
    _golden_path(
        "hg38",
        "Human GRCh38/hg38",
        "Homo sapiens",
        ("GRCh38",),
        f"{_UCSC}/gbdb/hg38/knownGene.bb",
        "chr17:7,661,779-7,687,538",
        "GENCODE genes",
    ),
    _golden_path(
        "hg19",
        "Human GRCh37/hg19",
        "Homo sapiens",
        ("GRCh37",),
        f"{_UCSC}/gbdb/hg19/knownGene.bb",
        "chr17:7,565,097-7,590,856",
        "GENCODE genes",
    ),
    _golden_path(
        "hs1",
        "Human T2T-CHM13v2.0/hs1",
        "Homo sapiens",
        ("T2T-CHM13v2.0", "CHM13", "chm13v2.0"),
        f"{_UCSC}/gbdb/hs1/ncbiRefSeq/ncbiRefSeq.bb",
        "chr17:7,480,000-7,510,000",
        "NCBI RefSeq genes",
    ),
    _golden_path(
        "mm10",
        "Mouse GRCm38/mm10",
        "Mus musculus",
        ("GRCm38",),
        f"{_UCSC}/gbdb/mm10/knownGene.bb",
        "chr11:69,580,359-69,591,873",
        "GENCODE genes",
    ),
    _golden_path(
        "mm39",
        "Mouse GRCm39/mm39",
        "Mus musculus",
        ("GRCm39",),
        _genark_bb("GCF_000001635.27", "GRCm39"),
        "chr11:69,471,185-69,482,699",
        "NCBI RefSeq genes",
    ),
    _golden_path(
        "sacCer3",
        "Yeast S288C R64/sacCer3",
        "Saccharomyces cerevisiae",
        ("R64", "R64-1-1"),
        _genark_bb("GCF_000146045.2", "R64"),
        "chrIV:1-100,000",
        "NCBI RefSeq genes",
    ),
    _golden_path(
        "dm6",
        "Fly BDGP6/dm6",
        "Drosophila melanogaster",
        ("BDGP6",),
        _genark_bb("GCF_000001215.4", "Release_6_plus_ISO1_MT"),
        "chr2L:1-100,000",
        "NCBI RefSeq genes",
    ),
    _golden_path(
        "ce11",
        "Worm WBcel235/ce11",
        "Caenorhabditis elegans",
        ("WBcel235",),
        _genark_bb("GCF_000002985.6", "WBcel235"),
        "chrI:1-100,000",
        "NCBI RefSeq genes",
    ),
    _golden_path(
        "danRer11",
        "Zebrafish GRCz11/danRer11",
        "Danio rerio",
        ("GRCz11",),
        _genark_bb("GCF_000002035.6", "GRCz11"),
        "chr1:1-200,000",
        "NCBI RefSeq genes",
    ),
    AssemblyPreset(
        name="TAIR10",
        display_name="Arabidopsis TAIR10",
        organism="Arabidopsis thaliana",
        twobit_uri=f"{_UCSC}/hubs/GCF/000/001/735/GCF_000001735.4/GCF_000001735.4.2bit",
        chrom_sizes_uri=(
            f"{_UCSC}/hubs/GCF/000/001/735/GCF_000001735.4/GCF_000001735.4.chrom.sizes.txt"
        ),
        chrom_alias_uri=(
            f"{_UCSC}/hubs/GCF/000/001/735/GCF_000001735.4/GCF_000001735.4.chromAlias.txt"
        ),
        aliases=("araTha1", "GCF_000001735.4"),
        annotation_uri=_genark_bb("GCF_000001735.4", "TAIR10.1"),
        annotation_name="NCBI RefSeq genes",
        default_location="NC_003070.9:1-100,000",
    ),
    _golden_path(
        "wuhCor1",
        "SARS-CoV-2 Wuhan-Hu-1/wuhCor1",
        "SARS-CoV-2",
        ("MN908947.3", "NC_045512.2", "SARS-CoV-2"),
        f"{_UCSC}/gbdb/wuhCor1/ncbiGene.bb",
        "NC_045512v2:1-29,903",
        "NCBI genes",
    ),
)

ASSEMBLY_PRESETS: dict[str, AssemblyPreset] = {p.name: p for p in _PRESETS}
_BY_ALIAS: dict[str, AssemblyPreset] = {
    alias.lower(): p for p in _PRESETS for alias in (p.name, *p.aliases)
}


def get_assembly_preset(name: str) -> AssemblyPreset | None:
    """Look a preset up by name or alias (case-insensitive)."""
    return _BY_ALIAS.get(name.strip().lower())


def list_assembly_presets() -> list[dict[str, Any]]:
    return [p.to_dict() for p in _PRESETS]


def _uri(uri: str) -> dict[str, str]:
    return {"uri": uri, "locationType": "UriLocation"}


PRESET_ROLES = ("twobit", "chrom_sizes", "aliases", "annotation")


def preset_file_uri(preset: AssemblyPreset, role: str) -> str | None:
    """The public URL of one file of a preset (the only URLs the preset proxy reads)."""
    return {
        "twobit": preset.twobit_uri,
        "chrom_sizes": preset.chrom_sizes_uri,
        "aliases": preset.chrom_alias_uri,
        "annotation": preset.annotation_uri,
    }.get(role)


def _direct(preset: AssemblyPreset, role: str) -> str:
    uri = preset_file_uri(preset, role)
    assert uri is not None
    return uri


# role → URL the browser should read: the upstream URL itself, or the API's
# preset proxy (see ``jbrowse_endpoints.proxy_preset_file``).
PresetUrlFor = Callable[[AssemblyPreset, str], str]


def preset_assembly_config(
    preset: AssemblyPreset, url_for: PresetUrlFor = _direct
) -> dict[str, Any]:
    """JBrowse ``assembly`` block for a preset."""
    return {
        "name": preset.name,
        "displayName": preset.display_name,
        "aliases": list(preset.aliases),
        "sequence": {
            "type": "ReferenceSequenceTrack",
            "trackId": f"{preset.name}-ReferenceSequenceTrack",
            "adapter": {
                "type": "TwoBitAdapter",
                "twoBitLocation": _uri(url_for(preset, "twobit")),
                "chromSizesLocation": _uri(url_for(preset, "chrom_sizes")),
            },
        },
        "refNameAliases": {
            "adapter": {
                "type": "RefNameAliasAdapter",
                "location": _uri(url_for(preset, "aliases")),
            }
        },
    }


def preset_annotation_track(
    preset: AssemblyPreset, url_for: PresetUrlFor = _direct
) -> dict[str, Any] | None:
    """Gene annotation track of a preset, or None when UCSC publishes none."""
    if not preset.annotation_uri:
        return None
    return {
        "type": "FeatureTrack",
        "trackId": f"{preset.name}-genes",
        "name": preset.annotation_name,
        "category": ["Annotation"],
        "assemblyNames": [preset.name],
        "adapter": {
            "type": "BigBedAdapter",
            "bigBedLocation": _uri(url_for(preset, "annotation")),
        },
    }
