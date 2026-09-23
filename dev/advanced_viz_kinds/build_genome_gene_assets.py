#!/usr/bin/env python3
"""Build the compact gene tables the ``genome_view`` annotation lane reads.

``@genome-spy/core`` ships chromosome *sizes* only (``genome/genomes.js``
exports ``getContigs(assembly)``), no gene models, so the annotation lane needs
an asset of its own. This script streams a GENCODE ``basic`` GTF over HTTP,
keeps the ``gene`` features whose ``gene_type`` is ``protein_coding`` on the
primary contigs, and writes one small JSON per assembly to
``depictio/viewer/public/assets/genomes/<assembly>.genes.json``.

The asset is deliberately array-of-arrays rather than array-of-objects: the
keys repeat once in ``columns`` instead of once per gene, which is what keeps
both files comfortably under the 1.5 MB budget the lane is allowed to download.

Nothing at runtime depends on this script; it is a build-time producer whose
output is committed. Re-run it only to move to a newer GENCODE release.

Examples
--------
    python dev/advanced_viz_kinds/build_genome_gene_assets.py --assembly hg38
    python dev/advanced_viz_kinds/build_genome_gene_assets.py \
        --assembly mm10 --release M25 --max-bytes 1500000

Sources (both CC BY 4.0, mirrored by EMBL-EBI):
    hg38 / GRCh38 -> Gencode_human/release_<N>/gencode.v<N>.basic.annotation.gtf.gz
    mm10 / GRCm38 -> Gencode_mouse/release_M25/gencode.vM25.basic.annotation.gtf.gz
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import urllib.request
from pathlib import Path

# Assembly -> (GENCODE species directory, default release, primary contigs).
# The contig list mirrors ``@genome-spy/core``'s built-in chrom.sizes tables so
# every gene in the asset lands on a contig the locus scale actually has.
ASSEMBLIES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "hg38": (
        "Gencode_human",
        "47",
        tuple(f"chr{c}" for c in [*range(1, 23), "X", "Y", "M"]),
    ),
    "mm10": (
        # M25 is the last GENCODE mouse release on GRCm38 (= mm10). Newer
        # releases are GRCm39 (= mm39), whose coordinates do not transfer.
        "Gencode_mouse",
        "M25",
        tuple(f"chr{c}" for c in [*range(1, 20), "X", "Y", "M"]),
    ),
}

BASE_URL = "https://ftp.ebi.ac.uk/pub/databases/gencode"

_ATTR = re.compile(r'(\S+) "([^"]*)"')


def gtf_url(assembly: str, release: str) -> str:
    species, _, _ = ASSEMBLIES[assembly]
    return f"{BASE_URL}/{species}/release_{release}/gencode.v{release}.basic.annotation.gtf.gz"


def parse_genes(handle, contigs: tuple[str, ...]) -> list[list[object]]:
    """Protein-coding ``gene`` rows on the primary contigs, in genome order."""
    keep = set(contigs)
    order = {name: i for i, name in enumerate(contigs)}
    rows: list[list[object]] = []
    for raw in handle:
        line = raw.decode("utf-8", "replace")
        if line.startswith("#"):
            continue
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 9 or parts[2] != "gene" or parts[0] not in keep:
            continue
        attrs = dict(_ATTR.findall(parts[8]))
        if attrs.get("gene_type") != "protein_coding":
            continue
        name = attrs.get("gene_name") or attrs.get("gene_id", "")
        if not name:
            continue
        rows.append([name, parts[0], int(parts[3]) - 1, int(parts[4]), parts[6]])
    rows.sort(key=lambda r: (order[str(r[1])], r[2]))
    return rows


def build(assembly: str, release: str, out_path: Path, max_bytes: int) -> int:
    species, _, contigs = ASSEMBLIES[assembly]
    url = gtf_url(assembly, release)
    print(f"[{assembly}] streaming {url}", file=sys.stderr)
    with urllib.request.urlopen(url) as resp, gzip.open(resp, "rb") as gz:
        genes = parse_genes(gz, contigs)
    print(f"[{assembly}] {len(genes)} protein-coding genes", file=sys.stderr)

    payload = {
        "assembly": assembly,
        "source": f"GENCODE {release} basic annotation ({species}), protein-coding genes",
        "url": url,
        "generated_by": "dev/advanced_viz_kinds/build_genome_gene_assets.py",
        "columns": ["name", "chrom", "start", "end", "strand"],
        "genes": genes,
    }
    # `separators` drops the space after every comma: ~4 % of the file.
    text = json.dumps(payload, separators=(",", ":"))
    size = len(text.encode("utf-8"))
    if size > max_bytes:
        raise SystemExit(
            f"[{assembly}] {size} bytes exceeds the {max_bytes} byte budget. "
            f"Raise --max-bytes deliberately, or narrow the gene set."
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text + "\n", encoding="utf-8")
    print(f"[{assembly}] wrote {out_path} ({size} bytes)", file=sys.stderr)
    return size


def gff3_url(assembly: str, release: str) -> str:
    species, _, _ = ASSEMBLIES[assembly]
    return f"{BASE_URL}/{species}/release_{release}/gencode.v{release}.basic.annotation.gff3.gz"


#: Feature types a transcript lane needs. Anything else (Selenocysteine,
#: start/stop codons) only makes the asset bigger.
GFF3_KEEP_TYPES = frozenset(
    {"gene", "transcript", "exon", "CDS", "five_prime_UTR", "three_prime_UTR"}
)


def build_gff3(assembly: str, release: str, out_path: Path) -> Path:
    """Write ``<assembly>.genes.gff3.gz`` plus its tabix index.

    A file-backed ``genome_view`` (``source: file``) draws its gene lane from a
    tabix-indexed GFF3 rather than the JSON table: the JSON is a flat gene list
    by design, which is what keeps it under a megabyte, and a file-backed track
    is already reading its own data over range requests, so it can afford real
    transcript models fetched the same way.

    ``bgzip`` and ``tabix`` (htslib) do the compression and the index. They are
    not a dependency of Depictio and this is a build-time producer, so their
    absence prints the command to run rather than failing the build.

    The output is tens of megabytes, which is why it is not committed: host it
    beside the JSON assets (``depictio/viewer/public/assets/genomes/``, served
    by the API's ``/dashboard/assets`` mount) or anywhere the browser can reach
    with CORS and HTTP range requests.
    """
    import shutil
    import subprocess

    missing = [tool for tool in ("bgzip", "tabix") if shutil.which(tool) is None]
    if missing:
        print(
            f"[{assembly}] {' and '.join(missing)} not found; skipping the GFF3 asset.\n"
            f"[{assembly}] Install htslib (brew install htslib, apt install tabix), then:\n"
            f"[{assembly}]   curl -sSL {gff3_url(assembly, release)} | gunzip \\\n"
            f"[{assembly}]     | grep -v '^#' | sort -k1,1 -k4,4n \\\n"
            f"[{assembly}]     | bgzip > {out_path}\n"
            f"[{assembly}]   tabix -f -p gff {out_path}",
            file=sys.stderr,
        )
        return out_path

    _, _, contigs = ASSEMBLIES[assembly]
    keep = set(contigs)
    order = {name: i for i, name in enumerate(contigs)}
    url = gff3_url(assembly, release)
    print(f"[{assembly}] streaming {url}", file=sys.stderr)

    # Sorted before bgzip: tabix needs contig then start order, and GENCODE's
    # own order is not the contig order the locus scale uses.
    rows: list[tuple[int, int, bytes]] = []
    with urllib.request.urlopen(url) as resp, gzip.open(resp, "rb") as gz:
        for raw in gz:
            if raw.startswith(b"#"):
                continue
            parts = raw.split(b"\t")
            if len(parts) < 9:
                continue
            chrom = parts[0].decode("utf-8", "replace")
            if chrom not in keep:
                continue
            if parts[2].decode("utf-8", "replace") not in GFF3_KEEP_TYPES:
                continue
            if b"gene_type=protein_coding" not in parts[8]:
                continue
            rows.append((order[chrom], int(parts[3]), raw))
    rows.sort(key=lambda r: (r[0], r[1]))
    print(f"[{assembly}] {len(rows)} features", file=sys.stderr)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as sink:
        proc = subprocess.Popen(["bgzip", "-c"], stdin=subprocess.PIPE, stdout=sink)
        assert proc.stdin is not None
        for _, _, raw in rows:
            proc.stdin.write(raw)
        proc.stdin.close()
        if proc.wait() != 0:
            raise SystemExit(f"[{assembly}] bgzip failed")
    subprocess.run(["tabix", "-f", "-p", "gff", str(out_path)], check=True)
    print(
        f"[{assembly}] wrote {out_path} ({out_path.stat().st_size} bytes) and {out_path}.tbi",
        file=sys.stderr,
    )
    return out_path


def main() -> None:
    repo = Path(__file__).resolve().parents[2]
    default_out = repo / "depictio" / "viewer" / "public" / "assets" / "genomes"

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--format",
        choices=("json", "gff3"),
        default="json",
        help=(
            "json: the compact gene table the table-backed annotation lane reads "
            "(committed). gff3: a tabix-indexed transcript annotation for "
            "file-backed tracks (not committed, tens of megabytes)."
        ),
    )
    parser.add_argument(
        "--assembly",
        action="append",
        choices=sorted(ASSEMBLIES),
        help="Assembly to build; repeatable. Default: every known assembly.",
    )
    parser.add_argument(
        "--release",
        default=None,
        help="GENCODE release for the single assembly being built (default: per-assembly)",
    )
    parser.add_argument("--out-dir", type=Path, default=default_out)
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=1_500_000,
        help="Refuse to write an asset larger than this (default: 1500000)",
    )
    args = parser.parse_args()

    assemblies = args.assembly or sorted(ASSEMBLIES)
    if args.release and len(assemblies) != 1:
        parser.error("--release applies to a single --assembly")

    for assembly in assemblies:
        release = args.release or ASSEMBLIES[assembly][1]
        if args.format == "gff3":
            build_gff3(assembly, release, args.out_dir / f"{assembly}.genes.gff3.gz")
        else:
            build(
                assembly,
                release,
                args.out_dir / f"{assembly}.genes.json",
                args.max_bytes,
            )


if __name__ == "__main__":
    main()
