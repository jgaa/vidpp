# Edited-Timeline Caption Transcription

## 1. Purpose

VidPP needs two different transcript roles:

1. an editorial transcript that preserves false starts, fillers, repetitions, and
   non-speech events so edit planning can see them;
2. an optional caption transcript made from the accepted, edited timeline and
   optimized for readable subtitles.

The editorial transcript remains the source of truth for editing. The caption
transcript is display text only and must never change an accepted edit plan.
All transcription remains local by default.

## 2. Default behavior

The default editorial transcriber is CrisperWhisper `small` in verbatim mode:

```yaml
version: 2
transcription:
  language: en
  phrases: []
  editorial:
    engine: crisperwhisper
    model: small
    backend: auto
  captions:
    engine: whisper
    model: turbo
```

Without an explicit CLI option, VidPP performs only editorial transcription and
builds captions by deterministically remapping the editorial transcript through
the accepted edit plan. This preserves the current single-pass workflow.

The second caption transcription pass is enabled explicitly:

```bash
vidpp process source.mp4 --caption-transcript
vidpp render project.vidpp --caption-transcript
```

The flag applies to the current command. A valid cached caption transcript may
be reused while the flag is present. Without the flag, rendering uses the
remapped editorial transcript even if an old caption transcript exists.

## 3. Configuration model

The nested `editorial` and `captions` roles replace the assumption that
`transcription.engine` selects one engine for every purpose.

Shared settings:

```yaml
transcription:
  language: en
  phrases:
    - VidPP
    - OneRSS
```

Role settings:

```yaml
transcription:
  editorial:
    engine: crisperwhisper  # crisperwhisper or whisper
    model: small
    backend: auto           # auto, transformers, or ct2; CrisperWhisper only
    recovery_model: turbo   # Whisper only
  captions:
    engine: whisper         # whisper or crisperwhisper
    model: turbo
    backend: auto
    recovery_model: turbo
```

Only settings relevant to the selected engine are used. Unsupported values and
unknown keys are errors rather than silent fallbacks.

Global and project phrase lists are normalized, combined, and deduplicated as
they are today. Both transcript roles receive the same effective language and
vocabulary unless a later specification adds role-specific overrides.

### 3.1 Backward compatibility

Version 1 configurations with flat keys remain valid:

```yaml
version: 1
transcription:
  engine: whisper
  model: turbo
```

Flat version 1 settings map to the `editorial` role. Caption-role defaults are
used if `--caption-transcript` is requested. New configurations should use
version 2 and must not mix flat engine/model keys with nested roles.

Existing environment variables continue to override the editorial role. Add
caption-specific equivalents:

```text
VIDPP_CAPTION_TRANSCRIBE_ENGINE
VIDPP_CAPTION_TRANSCRIBE_MODEL
VIDPP_CAPTION_CRISPER_BACKEND
VIDPP_CAPTION_WHISPER_RECOVERY_MODEL
```

Environment overrides do not implicitly enable the second pass; the CLI flag
is still required.

## 4. Transcript artifacts

Keep the two roles separate and inspectable:

```text
transcript.json                         editorial transcript, source timeline
cache/caption-audio.flac                edited, continuous transcription audio
cache/caption-transcript.raw.json       unmodified caption-engine result
caption-transcript.json                 validated display transcript, edited timeline
cache/caption-transcription-settings.json
```

`transcript.json` must never be overwritten by the caption pass.

Both transcript formats retain word timestamps and engine metadata. The caption
transcript timestamps are relative to the edited timeline and therefore must
not be remapped through `edit.json` again.

## 5. Processing pipeline

When `--caption-transcript` is enabled:

```text
source/master media
-> editorial transcription
-> analysis and edit planning
-> human-approved edit plan
-> construct continuous edited audio
-> duration-preserving pre-transcription audio filters
-> caption transcription with word timestamps
-> deterministic display-text sanitization
-> caption grouping and layout
-> final audio processing and loudness normalization
-> final render/mux
```

Construct `cache/caption-audio.flac` from exactly the enabled video edit
timeline. Use the same duration-preserving cut fades that the final video uses.
The audio must be continuous and start at edited-timeline time zero.

Use PCM or FLAC, not the final AAC stream, as transcription input. High-pass and
noise reduction may run before caption transcription when enabled because they
can improve recognition. Compression and loudness normalization may run later.
Every pre-transcription filter must preserve duration. Do not include background
music or unrelated mixed audio in the transcription input.

The caption pass is permitted when no edit is enabled; the explicit flag may be
used solely to obtain cleaner display text.

## 6. Engine behavior

Both Whisper and CrisperWhisper are valid caption transcribers.

Whisper is the default caption engine because it normally produces cleaner
display text and punctuation. It must use word timestamps, the configured
language, and the deduplicated vocabulary prompt.

CrisperWhisper remains available when its recognition is more accurate for a
speaker, accent, recording, or project vocabulary. It must run in the mode that
provides word timestamps. Its verbatim event annotations are preserved in the
raw artifact but removed from displayed subtitles as described below.

Engine loading, audio extraction, and transcription must emit INFO progress.
Effective settings, commands, cache decisions, word timestamps, and sanitized
tokens must be available at DEBUG level.

## 7. CrisperWhisper display sanitization

Never modify `cache/caption-transcript.raw.json`. Produce
`caption-transcript.json` through a deterministic token sanitization stage.

For displayed subtitles, remove recognized bracketed event annotations
case-insensitively, including common variants of:

```text
[UH] [UM] [PAUSE] [SILENCE] [BREATH] [BREATHING]
[COUGH] [COUGHING] [THROATCLEARING] [THROAT CLEARING]
[LAUGH] [LAUGHTER] [NOISE] [MUSIC]
```

Rules:

* remove only a maintained allowlist of known event tokens;
* do not remove arbitrary bracketed text;
* do not remove ordinary spoken words such as unbracketed `um` or `uh`;
* normalize whitespace and punctuation after removal;
* omit a caption unit that becomes empty;
* when removal exposes a sufficiently long timestamp gap, allow the normal
  caption pause logic to split the surrounding words;
* never stretch neighboring words across the removed event interval;
* log every removed token and its timestamp at DEBUG level.

These rules apply whenever CrisperWhisper supplies display captions, including
the single-pass fallback path. Editorial transcription remains verbatim.

## 8. Caption generation

Caption grouping consumes `caption-transcript.json` when the explicit caption
pass is enabled and valid. It otherwise consumes the editorial transcript after
mapping its word timestamps through enabled edits and applying the same display
sanitization rules when the editorial engine is CrisperWhisper.

Sentence punctuation, commas, measured text width, word count, character count,
speech pauses, and maximum duration remain deterministic layout concerns. The
caption transcriber does not choose visual caption boundaries.

## 9. Caching and invalidation

The caption-audio and caption-transcript cache fingerprint must include:

* source or combined-master identity;
* every enabled edit and its exact boundary;
* cut-fade settings;
* duration-preserving pre-transcription audio filters;
* caption engine, model, backend, and implementation version;
* language and effective deduplicated phrases;
* the event-token sanitization version.

Subtitle font, size, color, line width, and other layout settings do not
invalidate transcription.

Changing an enabled edit invalidates both caption audio and caption transcript.
Changing only visual styling reuses the caption transcript.

## 10. Failure behavior

The extra pass must not corrupt or replace a valid editorial transcript.

If caption audio construction or caption transcription fails:

1. retain all diagnostic artifacts;
2. log a clear warning;
3. fall back to the deterministically remapped editorial transcript;
4. sanitize CrisperWhisper event tokens before display;
5. continue rendering unless strict failure behavior is added explicitly later.

Invalid word timestamps, a duration mismatch, or caption words outside the
edited duration invalidate the caption transcript. Do not silently clamp or
invent timestamps.

## 11. Duration and synchronization requirements

The edited audio supplied to the caption engine and the edited video timeline
must have the same duration within the normal codec/container tolerance.

Final audio filters must preserve duration. Caption timestamps must remain
correct after final audio replacement or muxing. `-shortest` may be used only as
a final safeguard, not to hide a pipeline duration mismatch.

## 12. Testing

Unit tests must cover:

* version 2 role configuration and version 1 compatibility;
* CrisperWhisper `small` as the default editorial role;
* the CLI flag without implicit enablement from configuration;
* cache fingerprints changing with edits and transcription settings;
* word timestamps already being on the edited timeline;
* allowlisted event removal with case and spacing variants;
* preservation of unknown bracketed text and ordinary spoken filler words;
* empty-caption removal and pause-aware regrouping;
* fallback to remapped editorial words after caption-pass failure.

FFmpeg integration tests should generate a short fixture with a known removed
range, create edited FLAC audio, transcribe through a fake deterministic engine,
and verify that caption timestamps and final video duration follow the edited
timeline.

## 13. MVP acceptance criteria

The feature is complete when:

* a new project defaults to CrisperWhisper `small` for editorial transcription;
* normal rendering remains single-pass unless `--caption-transcript` is used;
* the flag produces or reuses a separate edited-timeline caption transcript;
* Whisper and CrisperWhisper can both serve as the caption engine;
* CrisperWhisper event annotations never appear in rendered subtitles;
* accepted video edits and caption timestamps remain synchronized;
* failures safely fall back to sanitized, remapped editorial captions;
* source media and the editorial transcript are never modified.
