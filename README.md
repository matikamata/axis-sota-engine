# 🎧 Sotā Engine

**A deterministic, cryptographically-sealed subtitle engine for Dhamma talks.**

Sotā takes a recorded Dhamma talk and produces multilingual subtitles where canonical Pāli terms are preserved exactly — never paraphrased, never lost in translation — with every output carrying a verifiable integrity seal.

The name *Sotā* is Pāli: both *the ear / that which listens* and *the stream* (as in stream-entry). The engine listens, and what it preserves is meant to outlast us.

Part of the [AXIS-NIDDHI](https://github.com/matikamata?tab=repositories) ecosystem for preserving and publishing Buddhist canonical knowledge as reproducible artifacts.

---

## Why this exists

Automatic YouTube captions are useless for Dhamma. Generic speech-to-text doesn't know Pāli, so canonical terms arrive distorted or silently dropped, and machine translation "normalizes" them into Western equivalents that lose the meaning. A talk that says *anicca* comes out as "impermanence"; *Nibbāna* drifts toward "Nirvana".

Sotā solves this with a glossary-lock: Pāli terms are swapped for opaque placeholders **before** any translation API sees the text, then restored afterward — so the translation engine never touches them. What survives is a master text where the Dhamma vocabulary is exactly as intended, ready to be multiplied into any number of languages.

The architecture follows a simple principle: **the machine flags, the human decides.** Where a Pāli term may have been lost (for example, through a speech-recognition error the glossary can't catch), the engine doesn't fail silently or guess — it quarantines the output for review by a native-fluent reviewer.

---

## How it works

The pipeline runs in three phases, each a separate script:

**Phase 0 — Capture & Crystallize** (`01_jarvis_phase0_*.py`)
Downloads the source, extracts a 48 kHz audio master (archived) and a 16 kHz band-passed proxy (for the model), transcribes with Whisper using a Pāli-biased initial prompt, and writes a structured, hashed transcript.

**Phase 1 — Translate, Bundle & Sign** (`02_full_script_*.py`)
Applies the three-layer glossary protection, translates via DeepL (with an optional LLM humanization pass), generates SRT subtitles, and seals everything into a bundle with a Merkle root and Ed25519 signatures.

**Verify** (`03_verify_*.py`)
Independently recomputes the integrity of any bundle offline and validates the signatures — provable trust, no network required.

```
source ─→ audio master (48k) ──────────────→ /archive  (sealed)
            └→ proxy (16k) ─→ Whisper ─→ structured transcript
                                              └→ glossary-lock ─→ DeepL ─→ restore
                                                    └→ SRT (per language)
                                                          └→ Merkle + Ed25519 ─→ bundle
```

---

## Pāli protection — three layers

1. **Transcription bias** — a Pāli term list is fed to Whisper as an initial prompt, nudging it to spell canonical terms correctly.
2. **Placeholder lock** — before translation, every protected term becomes an opaque token (`__PALI_LOCK_<hash>__`). The translation API never sees the Pāli. After translation, the canonical form is restored verbatim.
3. **Doctrinal safety** — the pipeline aborts if a forbidden term (signalling fabrication) appears, and quarantines the output if a protected Pāli term is lost.

The glossary itself is sealed into the integrity chain, so the exact vocabulary version is cryptographically bound to every output.

---

## Integrity model

Two seals, two authorities:

- **Cryptographic integrity** (machine) — Merkle root + Ed25519 signatures prove *this is exactly what the engine produced*. Verifiable offline by anyone.
- **Doctrinal approval** (human) — a native-fluent reviewer confirms the Pāli is faithful. Quarantined bundles carry `human_review_pending` until this seal is added.

A bundle can be cryptographically perfect and still await doctrinal review. The two are independent on purpose.

---

## Usage

Requirements: Python 3, `openai-whisper`, `pynacl`, `ffmpeg`, `yt-dlp`, and a DeepL API key.

```bash
# Configure secrets (never commit them — see run_hifi.sh.template)
export DEEPL_API_KEY="your-key-here"

# Phase 0 — capture and transcribe (interactive)
python 01_jarvis_phase0_*.py

# Phase 1 — translate and seal
python 02_full_script_*.py --input archive/<video_id>/raw_video.mp4 --channel @SourceChannel

# Verify any bundle
python 03_verify_*.py --bundle deliverables/<mode>/<video_id>/bundle/
```

Copy `run_hifi.sh.template` to `run_hifi.sh` and fill in your own paths and keys. The real `run_hifi.sh` is git-ignored — secrets stay on your machine.

---

## Status

Validated end-to-end in RAW mode (DeepL-only, no LLM pass): English → Brazilian Portuguese, on a real Dhamma talk. Cryptographic verification passes with full trust; the glossary-lock preserves canonical Pāli through translation.

**Working:** English-source ASR, EN→PT-BR translation with Pāli preservation, multilingual output in one pass, Merkle + Ed25519 sealing, quarantine routing.

**Not yet:** Sinhala-source ASR (no reliable off-the-shelf model — likely needs human transcription by native speakers), automatic normalization of truncated ASR terms, reconciliation with the full protection glossary.

---

## Lineage & licence

Built on the NEON-CHRONOS archival protocol. The glossary and Pāli vocabulary are curatorial work in service of faithful preservation.

This engine is offered in the spirit of *dāna* — a technical gift. Use it to preserve and share the Dhamma faithfully.

*Sādhu · Akāliko 🌸*
