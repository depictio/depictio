"""Copy a sarek ``-profile test`` run and put SYNTHETIC somatic calls into its paired VCFs.

The tiny ``-profile test`` run (one patient, tumour ``test2`` against normal ``test``,
``--tools strelka,mutect2,cnvkit,msisensorpro``) has paired VCFs with a header and no record, so
the Somatic calls and Germline vs somatic tabs of the nf-core/sarek template have nothing to
show. This writes made-up records into a COPY of the run so those tabs can be looked at. The
records are invented: they have no biological meaning and must never be shown as results. The
copy says so in a ``##synthetic`` header line of every VCF it touches, and the dashboard of a
project ingested from it is a demo of the layout only.

What it writes, in chr22 of the test genome (positions 1 to 40000):

* Mutect2 (``<tumour>_vs_<normal>.mutect2.filtered.vcf.gz``): SNVs and one indel, PASS and
  filtered, with a low tumour allele fraction and a near-zero normal one; two of the SNVs sit on
  positions the normal's own Strelka germline calls hold, so the "also in the normal" overlap
  is not empty;
* Strelka (``somatic_snvs`` and ``somatic_indels``): a few calls with the tier-1 counts Strelka
  writes.

Needs ``bgzip`` and ``tabix`` (htslib) on the PATH. Usage::

    python -m depictio.dev_scripts.sarek_synthetic_somatic SRC DEST [--tumour test2] [--normal test]

then ingest DEST like any run (``depictio-cli ingest --template nf-core/sarek/3.10.0
--data-root DEST``). It refuses to write over an existing DEST and never touches SRC.
"""

from __future__ import annotations

import argparse
import gzip
import random
import shutil
import subprocess
import sys
from pathlib import Path

BANNER = (
    "##synthetic=SYNTHETIC records written by depictio.dev_scripts.sarek_synthetic_somatic; "
    "not results"
)


def _read_vcf(path: Path) -> tuple[list[str], str]:
    """The header lines (without ``#CHROM``) and the ``#CHROM`` line of a VCF."""
    header: list[str] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if line.startswith("##"):
                header.append(line)
            elif line.startswith("#CHROM"):
                return header, line
    raise ValueError(f"{path}: no #CHROM line")


def _write_vcf(path: Path, header: list[str], chrom_line: str, records: list[str]) -> None:
    """Write a bgzipped, tabix-indexed VCF over ``path``."""
    bgzip, tabix = shutil.which("bgzip"), shutil.which("tabix")
    if not bgzip or not tabix:
        raise SystemExit("bgzip and tabix (htslib) are needed on the PATH")
    plain = path.with_suffix("")  # .../x.vcf
    body = [*header, BANNER, chrom_line, *records]
    plain.write_text("\n".join(body) + "\n", encoding="utf-8")
    path.unlink(missing_ok=True)
    path.with_name(path.name + ".tbi").unlink(missing_ok=True)
    subprocess.run([bgzip, "-f", str(plain)], check=True)
    subprocess.run([tabix, "-f", "-p", "vcf", str(path)], check=True)


def _mutect2_records(rng: random.Random, germline: list[tuple[int, str, str]]) -> list[str]:
    """SNVs and an indel in Mutect2's layout: GT:AD:AF:DP, normal column first.

    ``germline`` is the normal's PASS germline calls as (position, ref, alt): the first two
    are repeated as somatic calls with the same alleles, so the overlap with the normal is
    not empty.
    """
    bases = "ACGT"
    records = []
    shared = {pos: (ref, alt) for pos, ref, alt in germline[:2]}
    positions = sorted(set(rng.sample(range(2000, 39000), 9)) | set(shared))
    for pos in positions:
        in_normal = pos in shared
        if in_normal:
            ref, alt = shared[pos]
        else:
            ref = rng.choice(bases)
            alt = rng.choice([b for b in bases if b != ref])
        passed = in_normal or rng.random() < 0.7
        depth_t, depth_n = rng.randint(40, 120), rng.randint(40, 120)
        vaf_t = round(rng.uniform(0.05, 0.45), 3)
        # A call the normal's germline calls hold is carried by the normal too.
        vaf_n = round(rng.uniform(0.35, 0.55), 3) if in_normal else round(rng.uniform(0.0, 0.02), 3)
        alt_t, alt_n = round(depth_t * vaf_t), round(depth_n * vaf_n)
        flt = "PASS" if passed else rng.choice(["weak_evidence", "strand_bias", "germline"])
        tlod = round(rng.uniform(4.0, 40.0), 2)
        records.append(
            "\t".join(
                [
                    "chr22",
                    str(pos),
                    ".",
                    ref,
                    alt,
                    ".",
                    flt,
                    f"DP={depth_t + depth_n};TLOD={tlod}",
                    "GT:AD:AF:DP",
                    f"0/1:{depth_n - alt_n},{alt_n}:{vaf_n}:{depth_n}"
                    if in_normal
                    else f"0/0:{depth_n - alt_n},{alt_n}:{vaf_n}:{depth_n}",
                    f"0/1:{depth_t - alt_t},{alt_t}:{vaf_t}:{depth_t}",
                ]
            )
        )
    pos = rng.randint(3000, 38000)
    records.append(
        "\t".join(
            [
                "chr22",
                str(pos),
                ".",
                "CA",
                "C",
                ".",
                "PASS",
                "DP=150;TLOD=12.5",
                "GT:AD:AF:DP",
                "0/0:60,0:0.0:60",
                "0/1:63,27:0.3:90",
            ]
        )
    )
    return sorted(records, key=lambda r: int(r.split("\t")[1]))


def _strelka_snv_records(rng: random.Random) -> list[str]:
    """Strelka somatic SNVs: DP and the tier-1,2 base counts, NORMAL then TUMOR."""
    records = []
    for pos in sorted(rng.sample(range(2500, 38500), 4)):
        ref = rng.choice("ACGT")
        alt = rng.choice([b for b in "ACGT" if b != ref])
        depth = rng.randint(40, 100)
        alt_t = round(depth * rng.uniform(0.08, 0.4))

        def counts(n_alt: int, total: int) -> dict[str, str]:
            c = {b: "0,0" for b in "ACGT"}
            c[ref] = f"{total - n_alt},0"
            c[alt] = f"{n_alt},0"
            return c

        normal, tumour = counts(0, depth), counts(alt_t, depth)
        fmt = "DP:FDP:SDP:SUBDP:AU:CU:GU:TU"

        def col(c: dict[str, str]) -> str:
            return f"{depth}:0:0:0:{c['A']}:{c['C']}:{c['G']}:{c['T']}"

        flt = "PASS" if rng.random() < 0.75 else "LowEVS"
        records.append(
            "\t".join(
                [
                    "chr22",
                    str(pos),
                    ".",
                    ref,
                    alt,
                    ".",
                    flt,
                    f"SOMATIC;QSS=30;NT=ref;SomaticEVS={round(rng.uniform(5, 25), 2)}",
                    fmt,
                    col(normal),
                    col(tumour),
                ]
            )
        )
    return records


def _strelka_indel_records(rng: random.Random) -> list[str]:
    """Strelka somatic indels: DP, TAR and TIR (tier-1,2 reads), NORMAL then TUMOR."""
    records = []
    for pos in sorted(rng.sample(range(4000, 36000), 2)):
        tir = rng.randint(8, 30)
        tar = rng.randint(30, 70)
        records.append(
            "\t".join(
                [
                    "chr22",
                    str(pos),
                    ".",
                    "GT",
                    "G",
                    ".",
                    "PASS",
                    f"SOMATIC;QSI=20;SomaticEVS={round(rng.uniform(5, 20), 2)}",
                    "DP:DP2:TAR:TIR:TOR:DP50:FDP50:SUBDP50",
                    "70:70:70,70:0,0:0,0:70:0:0",
                    f"{tar + tir}:{tar + tir}:{tar},{tar}:{tir},{tir}:0,0:70:0:0",
                ]
            )
        )
    return records


def _germline_calls(strelka_germline: Path) -> list[tuple[int, str, str]]:
    """The normal's PASS germline calls as (position, ref, alt): some somatic calls repeat them."""
    calls = []
    with gzip.open(strelka_germline, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("#"):
                continue
            fields = line.split("\t")
            if fields[6] == "PASS":
                calls.append((int(fields[1]), fields[3], fields[4]))
    return calls


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("src", type=Path, help="a sarek -profile test run folder (read only)")
    parser.add_argument("dest", type=Path, help="where the modified copy goes (must not exist)")
    parser.add_argument("--tumour", default="test2", help="the tumour sample (default: test2)")
    parser.add_argument("--normal", default="test", help="the normal sample (default: test)")
    parser.add_argument("--seed", type=int, default=7, help="seed of the made-up records")
    args = parser.parse_args(argv)

    src, dest = args.src.expanduser(), args.dest.expanduser()
    if not src.is_dir():
        print(f"{src}: not a folder", file=sys.stderr)
        return 2
    if dest.exists():
        print(f"{dest}: exists, refusing to write over it", file=sys.stderr)
        return 2
    shutil.copytree(src, dest)

    pair = f"{args.tumour}_vs_{args.normal}"
    rng = random.Random(args.seed)
    germline = _germline_calls(
        dest / f"variant_calling/strelka/{args.normal}/{args.normal}.strelka.variants.vcf.gz"
    )
    targets = {
        dest / f"variant_calling/mutect2/{pair}/{pair}.mutect2.filtered.vcf.gz": _mutect2_records(
            rng, germline
        ),
        dest
        / f"variant_calling/strelka/{pair}/{pair}.strelka.somatic_snvs.vcf.gz": _strelka_snv_records(
            rng
        ),
        dest
        / f"variant_calling/strelka/{pair}/{pair}.strelka.somatic_indels.vcf.gz": _strelka_indel_records(
            rng
        ),
    }
    for path, records in targets.items():
        header, chrom_line = _read_vcf(path)
        _write_vcf(path, header, chrom_line, records)
        print(f"{path.relative_to(dest)}: {len(records)} synthetic records")
    print(f"done: {dest} (synthetic somatic calls; a layout demo, not results)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
