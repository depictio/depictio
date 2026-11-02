# nf-core wave: 11 release(s) — ❌3 🟡2 ⚪6

| Pipeline | Template → release | Verdict | Why | Report |
|---|---|---|---|---|
| `ampliseq` | 2.18.0 → 3.1.0 | ❌ review needed | major version bump 2.18.0 → 3.1.0 | `.nfcore-monitor/ampliseq-3.1.0.md` |
| `methylseq` | 2.3.0 → 4.2.0 | ❌ review needed | major version bump 2.3.0 → 4.2.0 | `.nfcore-monitor/methylseq-4.2.0.md` |
| `rnasplice` | 1.0.4 → 2.0.0 | ❌ review needed | major version bump 1.0.4 → 2.0.0 | `.nfcore-monitor/rnasplice-2.0.0.md` |
| `mhcquant` | 3.2.0 → 3.3.0 | 🟡 probable | 7 path(s) the template reads are unchanged; 1 directory change(s) elsewhere; 0 of 5 recipes ran | `.nfcore-monitor/mhcquant-3.3.0.md` |
| `variantbenchmarking` | 1.4.0 → 1.6.0 | 🟡 probable | 6 path(s) the template reads are unchanged; 2 directory change(s) elsewhere; 0 of 10 recipes ran | `.nfcore-monitor/variantbenchmarking-1.6.0.md` |
| `eager` | 2.4.5 → 2.5.3 | ⚪ unverified | no usable megatest run for this release | `.nfcore-monitor/eager-2.5.3.md` |
| `genomeassembler` | 2.0.0 → 2.0.1 | ⚪ unverified | no usable megatest run for this release | `.nfcore-monitor/genomeassembler-2.0.1.md` |
| `nanoseq` | 3.0.0 → 3.1.0 | ⚪ unverified | no usable megatest run for this release | `.nfcore-monitor/nanoseq-3.1.0.md` |
| `proteinfamilies` | 2.5.0 → 2.6.0 | ⚪ unverified | no usable megatest run for this release | `.nfcore-monitor/proteinfamilies-2.6.0.md` |
| `quantms` | 1.1.1 → 1.2.0 | ⚪ unverified | no usable megatest run for this release | `.nfcore-monitor/quantms-1.2.0.md` |
| `rnaseq` | 3.26.0 → 3.27.0 | ⚪ unverified | no usable megatest run for this release | `.nfcore-monitor/rnaseq-3.27.0.md` |

**How to ship:** bump the ✅ and 🟡 together in one PR, each ❌ in its own, and wait for a real run before bumping a ⚪ unless its changelog is trivial.
```
python scripts/bump_template_version.py --pipeline <name> --new-version <version>
```
This PR only carries the reports. Do not merge it: close it once the wave is handled; the next run reopens one.
