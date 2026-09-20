# VidPP Audio Processing

## 1. Goal

VidPP should improve spoken-word audio while preserving a natural voice. Audio
processing must be local, deterministic, configurable, and independent of the
LLM editing stage. FFmpeg performs the processing.

The MVP targets ordinary phone, camera, and external-microphone recordings. It
does not attempt professional restoration or repair of clipped microphones,
severe wind distortion, or arbitrary foreground sounds.

## 2. Processing model

Timeline editing and audio enhancement are separate stages. VidPP first creates
a continuous edited master, then processes that master's audio, and finally
replaces the master's audio track without re-encoding its video.

```text
source media
    |
    v
timeline edits and duration-preserving cut fades
    |
    v
edited master video + continuous lossless audio
    |
    v
optional high-pass filter
    |
    v
optional noise reduction
    |
    v
optional speech compression
    |
    v
two-pass loudness normalization
    |
    v
final audio encode and mux, with video copied unchanged
```

This ordering is required. Audio filters must not run independently on edit
fragments because resetting filter state at every cut can create audible
changes. Do not repeatedly encode audio between stages.

The edited intermediate audio should be PCM or FLAC. Final audio may be encoded
to a container-compatible codec such as AAC for MP4. The final mux should use
stream copy for the already-rendered video.

## 3. Configuration

Extend the VidPP template with an `audio` section:

```yaml
audio:
  enabled: true

  highpass:
    enabled: false
    frequency: 80

  noise_reduction:
    enabled: false
    mode: afftdn
    strength: moderate

  compression:
    enabled: false
    mode: speech

  loudness:
    enabled: true
    target_lufs: -16
    loudness_range: 11
    true_peak: -1.5
```

Defaults must be conservative:

* loudness normalization is enabled;
* high-pass filtering, noise reduction, and compression are opt-in;
* source channel layout is preserved.

Project files contain semantic settings, never FFmpeg filter graphs. Each stage
is independently configurable. Validate settings before starting a render.
Initial validation limits are:

* high-pass frequency: 20-300 Hz;
* loudness target: -24 to -10 LUFS;
* loudness range: 1-20 LU;
* true peak: -9 to -0.1 dBTP;
* noise strength: `light`, `moderate`, or `strong`.

## 4. Edited master

All video cuts, pause shortening, scaling, rotation, overlays, and captions are
completed before audio enhancement. Corresponding audio cuts use the same
edited timeline, producing a continuous stream with exactly the master's
duration.

Retain useful master and audio artifacts in the cache so audio settings can be
changed without rendering the video again. An implementation may use:

```text
cache/edited-master.mkv
cache/edited-audio.flac
cache/processed-audio.flac
output/final.mp4
```

Artifact names and containers are implementation details, not part of the
persistent project format.

## 5. Cut boundaries

Speech cuts must not introduce clicks. For the MVP, apply very short fade-out
and fade-in envelopes at audio cut boundaries while constructing the edited
timeline. These envelopes preserve duration and are not requested by the LLM.

Do not overlap adjacent audio with a crossfade unless the matching video edit
uses the same overlap. An audio-only overlap can change duration, reintroduce
removed speech, and break A/V synchronization.

## 6. Analysis and caching

Collect source metadata with ffprobe:

* selected audio stream and codec;
* sample rate and channel layout/count;
* duration;
* maximum sample peak where useful.

Store source metadata separately from measurements of edited and filtered
audio. For example:

```json
{
  "source_audio": {
    "codec": "aac",
    "sample_rate": 48000,
    "channels": 2,
    "duration": 42.1
  },
  "render_audio": {
    "integrated_lufs": -23.4,
    "loudness_range": 8.2,
    "true_peak_dbtp": -4.1
  }
}
```

Reusable measurements belong in `analysis.json`. A cached render measurement
is valid only when its fingerprint includes:

* source-media identity;
* the applied timeline/edit plan;
* every audio setting before and including loudness normalization;
* the relevant FFmpeg/filter implementation version.

Do not reuse measurements merely because the source file is unchanged.

## 7. Loudness normalization

Use FFmpeg's `loudnorm` filter with a proper two-pass process:

1. run the edited continuous audio through every enabled filter preceding
   `loudnorm` and collect its measurements;
2. run the same filter chain with those measurements supplied to `loudnorm`,
   then encode the final audio.

Default targets are -16 LUFS integrated loudness, 11 LU loudness range, and
-1.5 dBTP true peak.

Normalization is deterministic when enabled; the MVP does not automatically
bypass it based on a closeness threshold. It must not be implemented as a
simple peak-gain adjustment.

Where `loudnorm` provides the required true-peak control, do not add another
limiter. Introduce one only if final-output verification demonstrates a need.

## 8. Optional filters

The optional high-pass filter removes low-frequency rumble and moderate wind
noise. Use conservative settings and do not claim it can recover an overloaded
or clipped microphone signal.

The MVP supports local FFmpeg `afftdn` noise reduction. Map `light`, `moderate`,
and `strong` to tested internal settings. Processing must never upload audio.
Additional local denoisers such as `anlmdn` and `arnndn` are future work. An
`arnndn` implementation requires an explicitly configured local model and must
validate it before a long render begins.

The optional `speech` compression preset uses deliberately mild dynamic-range
compression. Compression occurs before loudness measurement and normalization;
its FFmpeg parameters remain an implementation detail.

## 9. Streams, channels, and synchronization

Preserve source channel layout by default; speech must not automatically be
converted from stereo to mono. Explicit mono output can be added later.

Use the source's default audio stream, or the first audio stream when none is
marked default. Explicit stream selection may be added later. A video with no
audio remains valid: log that processing was skipped and render without an
audio track.

Processed audio duration must match the edited master. FFmpeg `-shortest` may
be a safeguard, but must not hide a synchronization bug. Integration tests must
verify final A/V duration and synchronization.

## 10. Preview and comparison

Normal previews use the final audio pipeline so users can judge denoising and
compression. `vidpp preview --fast` may bypass audio enhancement, but must say
so in its log output.

A later comparison command may produce short lossless samples without rendering
the whole video:

```bash
vidpp audio preview project/ --start 30 --duration 15
```

Do not add audio-specific commands until they materially help users or
development.

## 11. FFmpeg integration and failures

Build filter graphs internally and invoke FFmpeg with subprocess argument
arrays, never through a shell. Debug logging includes configuration and cache
decisions, measurements, and complete argument arrays. Trace logging preserves
enough filter and command context to reproduce a failure.

Before rendering, validate requested filters, codecs, and model files. On
failure, report the semantic stage, relevant FFmpeg filter, missing capability
or model when applicable, and useful FFmpeg diagnostics. Never silently use
unprocessed audio when explicitly requested processing fails.

## 12. Testing

Add unit tests for configuration defaults and validation, filter generation,
two-pass `loudnorm` parsing, cache invalidation, and missing optional
capabilities.

Use FFmpeg-generated media for integration tests covering mono and stereo,
different sample rates, no-audio input, timeline cuts and cut fades, final remux
without video re-encoding, A/V synchronization, and output loudness reasonably
close to the configured target. Do not compare encoded files byte-for-byte.

## 13. Implementation order

1. source audio metadata;
2. lossless continuous audio from the edited timeline;
3. duration-preserving cut fades;
4. two-pass `loudnorm` over the edited audio;
5. audio-only final mux with video stream copy;
6. high-pass filtering;
7. `afftdn` noise reduction;
8. conservative speech compression;
9. preview and comparison tools;
10. additional denoisers and deterministic automatic processing.

The first useful milestone is: **VidPP can reuse a completed video edit and
produce consistently leveled speech audio without clipping, re-encoding the
video, or losing A/V synchronization.**
