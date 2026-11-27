# nf-core wave: 5 release(s) — ❌1 🟡1 ⚪3

| Pipeline | Template → release | Verdict | Why | Report |
|---|---|---|---|---|
| `methylseq` | 2.3.0 → 4.2.0 | ❌ review needed | major version bump 2.3.0 → 4.2.0 | `.nfcore-monitor/methylseq-4.2.0.md` |
| `pairgenomealign` | 3.0.4 → 3.0.5 | 🟡 probable | 8 path(s) the template reads are unchanged; 0 of 7 recipes ran | `.nfcore-monitor/pairgenomealign-3.0.5.md` |
| `genomeassembler` | 2.0.0 → 2.0.1 | ⚪ unverified | no usable megatest run for this release | `.nfcore-monitor/genomeassembler-2.0.1.md` |
| `nanoseq` | 3.0.0 → 3.1.0 | ⚪ unverified | no usable megatest run for this release | `.nfcore-monitor/nanoseq-3.1.0.md` |
| `rnafusion` | 4.1.3 → 4.2.0 | ⚪ unverified | no usable megatest run for this release | `.nfcore-monitor/rnafusion-4.2.0.md` |

**How to ship:** bump the ✅ and 🟡 together in one PR, each ❌ in its own, and wait for a real run before bumping a ⚪ unless its changelog is trivial.
```
python scripts/bump_template_version.py --pipeline <name> --new-version <version>
```
This PR only carries the reports. Do not merge it: close it once the wave is handled; the next run reopens one.
