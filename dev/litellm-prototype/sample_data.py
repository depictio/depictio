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


def compute_data_profile(df: pd.DataFrame) -> str:
    """Run real pandas operations and return a comprehensive text profile.

    This gives the LLM actual computed statistics to reason about,
    not just metadata. All operations are logged to the terminal.
    """
    import logging

    logger = logging.getLogger("data_profile")
    sections = []

    # --- 1. Shape & dtypes ---
    logger.info("─── Computing: shape & dtypes ───")
    sections.append(f"SHAPE: {df.shape[0]} rows x {df.shape[1]} columns")

    # --- 2. df.describe() for numeric columns ---
    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    if numeric_cols:
        logger.info("─── Computing: df.describe() on %s ───", numeric_cols)
        desc = df[numeric_cols].describe().round(3)
        sections.append(f"DESCRIPTIVE STATISTICS (numeric):\n{desc.to_string()}")

        # --- 3. Correlation matrix ---
        if len(numeric_cols) >= 2:
            logger.info("─── Computing: df[%s].corr() ───", numeric_cols)
            corr = df[numeric_cols].corr().round(3)
            sections.append(f"CORRELATION MATRIX:\n{corr.to_string()}")

        # --- 4. Null counts ---
        logger.info("─── Computing: df.isnull().sum() ───")
        nulls = df[numeric_cols].isnull().sum()
        if nulls.any():
            sections.append(f"NULL COUNTS:\n{nulls.to_string()}")
        else:
            sections.append("NULL COUNTS: none")

    # --- 5. Categorical columns: value counts ---
    cat_cols = df.select_dtypes(include=["object", "category"]).columns.tolist()
    for col in cat_cols:
        logger.info("─── Computing: df['%s'].value_counts() ───", col)
        vc = df[col].value_counts()
        sections.append(f"VALUE COUNTS for '{col}':\n{vc.to_string()}")

    # --- 6. Group-by stats (categorical × numeric) ---
    if cat_cols and numeric_cols:
        for cat_col in cat_cols[:2]:  # max 2 categorical columns
            logger.info("─── Computing: df.groupby('%s')[%s].agg(['mean','std','count']) ───", cat_col, numeric_cols)
            grouped = df.groupby(cat_col)[numeric_cols].agg(["mean", "std", "count"]).round(3)
            sections.append(f"GROUP-BY '{cat_col}' STATISTICS:\n{grouped.to_string()}")

    # --- 7. Sample rows ---
    logger.info("─── Computing: df.head(5) + df.tail(5) ───")
    sections.append(f"FIRST 5 ROWS:\n{df.head(5).to_string(index=False)}")
    sections.append(f"LAST 5 ROWS:\n{df.tail(5).to_string(index=False)}")

    profile = "\n\n".join(sections)
    logger.info("─── Data profile complete: %d chars ───", len(profile))
    return profile
