# Snelheid met TEI aan 2026-09-26 (ST-002 T-8)

Dezelfde meting als `speed-2026-09-25.md`, maar met TEI (bge-m3, ~2,5 GB VRAM) weer actief: de
normale toestand van max2. Mediaan van 2 runs, thinking uit. Bron: `speed-2026-09-26-tei-on/`.
Bij 2 runs is de mediaan het gemiddelde van beide runs, dus een uitschieter telt volledig mee (bijv.
qwen3-coder 16k kort: 60,2 en 69,9 tok/s). De tabel is daardoor minder scherp dan de 3-run-medianen van T-4.

| Model | GPU % 16k / 32k | Genereren tok/s kort / lang, 16k | idem 32k | Zonder TEI (32k, uit T-4) |
|---|---|---|---|---|
| qwen3.6:35b-a3b-coding | 49 / 49 | 99 / 79 | 95 / 80 | 118 / 98 |
| qwen3-coder:30b | 63 / 60 | 65 / 61 | 61 / 59 | 84 / 79 |
| qwen3.8-gsq-rco:27b-iq3_s-text (zonder vision-projector) | 95 / 90 | 42 / 41 | 23 / 22 | – |
| qwen3.8-gsq-rco:27b-iq3_s | 88 / 83 | 18 / 18 | 14 / 13 | 55 / 53 |

- Een dense model valt hard terug zodra een deel naar de CPU moet. Tegenover 53 tok/s volledig op de GPU
  (32k, TEI uit): de `-text`-variant haalt 41 tok/s op 95% GPU (16k) en 22 tok/s op 90% (32k);
  GSQ-RCO IQ3_S met projector zakt op 83% GPU (32k) naar 13 tok/s. De MoE-modellen (3B actief)
  verliezen ~20% (qwen3.6) tot ~25% (qwen3-coder).
- `qwen3.8-gsq-rco:27b-iq3_s-text` (`modelfiles/qwen3.8-gsq-rco-iq3_s-text.Modelfile`) laat de vision-
  projector (~0,9 GB) weg; bij 16k context haalt het dan nog 41 tok/s naast TEI. Het past niet volledig:
  ook zonder projector staat 5% (16k) tot 10% (32k) op de CPU.
