"""Sample datasets for the AI dashboard prototype."""

import numpy as np
import pandas as pd


def get_iris_data() -> pd.DataFrame:
    """Classic iris dataset — 150 rows, 5 columns."""
    np.random.seed(42)
    n = 50
    data = []
    for variety, sl, sw, pl, pw in [
        ("setosa", 5.0, 3.4, 1.5, 0.2),
        ("versicolor", 5.9, 2.8, 4.3, 1.3),
        ("virginica", 6.6, 3.0, 5.6, 2.0),
    ]:
        data.append(
            pd.DataFrame(
                {
                    "sepal_length": np.random.normal(sl, 0.35, n).round(1),
                    "sepal_width": np.random.normal(sw, 0.38, n).round(1),
                    "petal_length": np.random.normal(pl, 0.17 if variety == "setosa" else 0.47, n).round(1),
                    "petal_width": np.random.normal(pw, 0.10 if variety == "setosa" else 0.20, n).round(1),
                    "variety": variety,
                }
            )
        )
    return pd.concat(data, ignore_index=True)


def get_genomics_qc_data() -> pd.DataFrame:
    """Synthetic genomics QC dataset — 200 rows, 7 columns."""
    np.random.seed(123)
    n = 200
    library_types = np.random.choice(["WGS", "WES", "RNA-seq", "ChIP-seq"], n, p=[0.3, 0.25, 0.3, 0.15])
    total_reads = np.random.lognormal(mean=17.5, sigma=0.5, size=n).astype(int)
    mapping_rate = np.clip(np.random.beta(30, 3, n) * 100, 50, 99.9).round(1)
    gc_content = np.clip(np.random.normal(45, 5, n), 25, 65).round(1)
    duplication_rate = np.clip(np.random.exponential(8, n), 1, 50).round(1)

    # Status based on QC thresholds
    status = np.where(
        (mapping_rate > 80) & (duplication_rate < 20),
        "PASS",
        np.where(
            (mapping_rate > 70) & (duplication_rate < 30),
            "WARNING",
            "FAIL",
        ),
    )

    return pd.DataFrame(
        {
            "sample_id": [f"SAMPLE_{i:04d}" for i in range(n)],
            "total_reads": total_reads,
            "mapping_rate": mapping_rate,
            "gc_content": gc_content,
            "duplication_rate": duplication_rate,
            "library_type": library_types,
            "status": status,
        }
    )


DATASETS = {
    "iris": {"loader": get_iris_data, "label": "Iris (Botanical)"},
    "genomics_qc": {"loader": get_genomics_qc_data, "label": "Genomics QC"},
}


def get_column_metadata(df: pd.DataFrame) -> str:
    """Build a text summary of columns for LLM context."""
    lines = []
    for col in df.columns:
        dtype = str(df[col].dtype)
        if pd.api.types.is_numeric_dtype(df[col]):
            stats = f"min={df[col].min()}, max={df[col].max()}, mean={df[col].mean():.2f}"
        else:
            uniq = df[col].nunique()
            examples = df[col].unique()[:5].tolist()
            stats = f"unique={uniq}, examples={examples}"
        lines.append(f"  - {col} ({dtype}): {stats}")
    return f"Columns ({len(df)} rows):\n" + "\n".join(lines)
