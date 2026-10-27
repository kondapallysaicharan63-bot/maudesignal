# Skill: dossier-cover-illustration

**Version:** 1.0.0 (HACKATHON-BUILT — Meta Global AI Developer Hackathon, Oct 26 – Nov 4, 2026)
**Model:** Meta Muse Image (`muse-image-1.0`) via `POST /v1/images/generations`
**Consumers:** `maudesignal.dossier.illustration.generate_illustration`

Optional, OFF by default. Produces one decorative cover illustration for a
Signal Evaluation & CAPA record. The image is captioned "AI-generated
illustration — not evidence" and is placed only on the cover page, never in
the signal, evidence, CAPA, MDR or audit sections. Cost: $0.01 per image.

## Rules

- Abstract and non-photorealistic. No people, patients, body parts, clinical
  scenes, logos, brand names, device photos, charts, numbers or text.
- The prompt receives only the product code's classification name (a public
  FDA category), never report narratives.

## Prompt template

The text between the markers is sent as `prompt`; `{classification}` is
replaced with the openFDA classification name.

<!-- PROMPT START -->
Abstract minimalist cover art for a medical-device quality report about the category "{classification}". Soft geometric shapes, muted navy and slate-grey palette, clean flat vector style, lots of white space. No text, no letters, no numbers, no logos, no people, no body parts, no charts.
<!-- PROMPT END -->

## Changelog

- 1.0.0 (2026-10-27): initial version.
