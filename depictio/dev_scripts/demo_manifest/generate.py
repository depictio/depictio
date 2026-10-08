"""Generate a self-contained Data Manifest demo dataset.

Writes synthetic per-sample CSVs plus a ``manifest.json``/``manifest.csv``
whose entry URLs are absolute (built from ``--base-url``), ready to serve with
any static file server and feed to the ``generic/manifest-tables/1`` template:

    python depictio/dev_scripts/demo_manifest/generate.py \
        --base-url http://host.docker.internal:8099 \
        --output-dir demo-manifest-data
    cd demo-manifest-data && python -m http.server 8099 --bind 0.0.0.0

See README.md next to this script for the full walkthrough (including the
SSRF-gateway environment variables a local HTTP server requires).
"""

import argparse
import csv
import json
import random
from pathlib import Path

SAMPLES = ["sample_A", "sample_B", "sample_C"]
CONDITIONS = {"sample_A": "control", "sample_B": "treated", "sample_C": "treated"}


def _write_sample_csv(path: Path, sample: str, rng: random.Random) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["cell_id", "condition", "batch", "quality_score", "read_count"])
        for i in range(rng.randint(40, 60)):
            writer.writerow(
                [
                    f"{sample}_cell{i:03d}",
                    CONDITIONS[sample],
                    rng.choice(["b1", "b2"]),
                    round(rng.uniform(0.5, 1.0), 3),
                    rng.randint(1_000, 50_000),
                ]
            )


def _write_measurements_csv(path: Path, sample: str, rng: random.Random) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["feature", "value", "pvalue"])
        for feature in [f"gene_{chr(ord('a') + i)}" for i in range(20)]:
            writer.writerow(
                [feature, round(rng.gauss(10, 3), 3), round(rng.uniform(0.0001, 0.2), 5)]
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        required=True,
        help="Absolute URL prefix under which --output-dir will be served, "
        "e.g. http://host.docker.internal:8099 or https://my-bucket.s3.amazonaws.com/demo",
    )
    parser.add_argument("--output-dir", default="demo-manifest-data", type=Path)
    parser.add_argument("--seed", default=42, type=int)
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    out: Path = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)

    entries = []
    for sample in SAMPLES:
        samples_file = f"{sample}.samples.csv"
        measurements_file = f"{sample}.measurements.csv"
        _write_sample_csv(out / samples_file, sample, rng)
        _write_measurements_csv(out / measurements_file, sample, rng)
        entries.append(
            {"id": sample, "type": "samples", "url": f"{base}/{samples_file}", "run": "demo_run"}
        )
        entries.append(
            {
                "id": sample,
                "type": "measurements",
                "url": f"{base}/{measurements_file}",
                "run": "demo_run",
            }
        )

    (out / "manifest.json").write_text(json.dumps(entries, indent=2) + "\n")
    with (out / "manifest.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["id", "type", "url", "run"])
        writer.writeheader()
        writer.writerows(entries)

    print(f"Wrote {len(entries)} manifest entries + {2 * len(SAMPLES)} CSVs to {out}/")
    print(f"Manifest URL once served: {base}/manifest.json")


if __name__ == "__main__":
    main()
