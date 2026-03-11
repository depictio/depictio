#!/usr/bin/env bash
# download_nfcore_trees.sh
#
# Downloads example phylogenetic trees from nf-core pipeline test results
# into dev/phylogenetic-trees/data/nfcore/ for use with the prototype apps.
#
# Usage:
#   cd dev/phylogenetic-trees && bash download_nfcore_trees.sh
#
# Sources:
#   - ampliseq 2.16.0: QIIME2 rooted phylogenetic tree (Newick)
#   - viralrecon 3.0.0: Nextclade Auspice JSON v2 tree → converted to Newick

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${SCRIPT_DIR}/data/nfcore"
mkdir -p "${DATA_DIR}"

AMPLISEQ_BASE="https://nf-co.re/ampliseq/2.16.0/results/ampliseq/results-3d5c7e5bec28de279337f3ffe3c312a45940b782"
VIRALRECON_BASE="https://nf-co.re/viralrecon/3.0.0/results/viralrecon/results-395079f1d24dce731ac22e03d7a5e71f110103fc"

echo "=== Downloading nf-core pipeline example trees ==="
echo ""

# --------------------------------------------------------------------------
# 1. ampliseq: QIIME2 phylogenetic tree (already Newick format)
# --------------------------------------------------------------------------
echo "[1/2] ampliseq — QIIME2 rooted phylogenetic tree"
if curl -fSL --progress-bar \
    "${AMPLISEQ_BASE}/qiime2/phylogenetic_tree/tree.nwk" \
    -o "${DATA_DIR}/ampliseq_tree.nwk"; then
    echo "  -> Saved: ${DATA_DIR}/ampliseq_tree.nwk"
else
    echo "  !! Failed to download ampliseq tree. The nf-core results URL may have changed."
    echo "  !! Check: ${AMPLISEQ_BASE}"
fi
echo ""

# --------------------------------------------------------------------------
# 2. viralrecon: Nextclade Auspice JSON tree → convert to Newick
#    Nextclade outputs Auspice JSON v2, not Newick. We download the JSON
#    and convert it using auspice_to_newick.py.
# --------------------------------------------------------------------------
echo "[2/2] viralrecon — Nextclade Auspice JSON tree"
AUSPICE_JSON="${DATA_DIR}/viralrecon_nextclade.auspice.json"
NEWICK_OUT="${DATA_DIR}/viralrecon_tree.nwk"

if curl -fSL --progress-bar \
    "${VIRALRECON_BASE}/variants/ivar/nextclade/nextclade.auspice.json" \
    -o "${AUSPICE_JSON}"; then
    echo "  -> Saved: ${AUSPICE_JSON}"

    # Convert Auspice JSON to Newick
    if python3 "${SCRIPT_DIR}/auspice_to_newick.py" "${AUSPICE_JSON}" "${NEWICK_OUT}"; then
        echo "  -> Converted to: ${NEWICK_OUT}"
    else
        echo "  !! Conversion to Newick failed. The JSON is still available at:"
        echo "     ${AUSPICE_JSON}"
    fi
else
    echo "  !! Failed to download viralrecon Nextclade tree."
    echo "  !! Check: ${VIRALRECON_BASE}"
fi

echo ""
echo "=== Done ==="
echo "Downloaded trees:"
ls -lh "${DATA_DIR}"/*.nwk 2>/dev/null || echo "  (no .nwk files found)"
