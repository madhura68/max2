# Bewijs dev-docker (IDEA-258)

| Bestand | Inhoud | Herkomst |
|---|---|---|
| `2026-10-12-p6-memavailable-max2.csv` | 1584 samples (≈ 60 s-interval: de sampler doet `vmstat 1 5` plus `sleep 55`) van load, CPU, `mem_avail_kb`, swap, GPU en schijf op max2 onder N = 2-productielast, 2026-10-12T10:46:54Z – 2026-10-13T12:46:02Z. Minimum `mem_avail_kb` = 22 576 424 (21,53 GiB) om 2026-10-12T12:28:21Z; maximum 27 449 024 (26,18 GiB). | Byte-identieke kopie van `max2:~/m52-p6/metrics.csv` (P6-meting uit `scrum4me-server/docs/forgejo-runner-pool/evidence/n-stacks/2026-10-12-uitrol-stack-03.md`), gekopieerd 2026-10-14. sha256 `64afdefca9611ebbb3c0f0baa7fe034f6efb5e7dd2d809ddbb7c352f2b6be329`. |
| `2026-10-12-p6-sampler.sh` | De sampler die de reeks produceerde. | Kopie van `max2:~/m52-p6/sampler.sh`. |

Gebruik: invoer voor de headroomgate in `dev-docker/SPEC.md` §8 (`--series 21.53:…`). Geen secrets; alleen hostmetrieken.
