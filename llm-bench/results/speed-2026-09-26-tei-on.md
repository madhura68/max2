# Snelheid met TEI aan 2026-09-26 (ST-002 T-8)

Dezelfde meting als `speed-2026-09-25.md`, maar met TEI (bge-m3, ~2,5 GB VRAM) weer actief: de
normale toestand van max2. Mediaan van 2 runs, thinking uit. Bron: `speed-2026-09-26-tei-on/`.

| Model | GPU % 16k / 32k | Genereren tok/s kort / lang, 16k | idem 32k | Zonder TEI (32k, uit T-4) |
|---|---|---|---|---|
| qwen3.6:35b-a3b-coding | 49 / 49 | 99 / 79 | 95 / 80 | 118 / 98 |
| qwen3-coder:30b | 63 / 60 | 65 / 61 | 61 / 59 | 84 / 79 |
| qwen3.8-gsq-rco:27b-iq3_s-text (zonder vision-projector) | 95 / 90 | 42 / 41 | 23 / 22 | – |
| qwen3.8-gsq-rco:27b-iq3_s | 88 / 83 | 18 / 18 | 14 / 13 | 55 / 53 |

- Een dense model valt hard terug zodra er ook maar een paar procent naar de CPU moet: GSQ-RCO IQ3_S
  gaat van 53 naar 13 tok/s. De MoE-modellen (3B actief) verliezen maar ~20%.
- `qwen3.8-gsq-rco:27b-iq3_s-text` (`modelfiles/qwen3.8-gsq-rco-iq3_s-text.Modelfile`) laat de vision-
  projector (~0,9 GB) weg; bij 16k context haalt het dan nog 41 tok/s naast TEI.
