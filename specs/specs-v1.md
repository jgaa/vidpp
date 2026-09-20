# Automated Social Video Post-Processor

## 1. Goal

Create a local, CLI-based video post-processing tool for simple social-media videos.

The initial use case is a single person speaking to a camera. The user provides a source video and optionally a visual template/configuration. The tool analyzes the speech, proposes sensible edits, renders subtitles and optional branding/graphics, and produces a finished social-media video.

The application must be designed so that a Qt/QML GUI can be added later without rewriting the processing engine.

The initial implementation should prioritize:

* simplicity;
* deterministic and reproducible rendering;
* local processing;
* non-destructive editing;
* good output quality;
* inspectable intermediate files;
* easy experimentation with prompts and editing policies.

Do not attempt to build a general-purpose nonlinear video editor.

---

# 2. Technology

Use:

* Python 3.12+ for the application and CLI;
* FFmpeg/ffprobe for video/audio processing;
* JSON for persistent project and edit-plan formats;
* a local LLM through an OpenAI-compatible HTTP API;
* Qwen3-class small models as the initial target;
* Whisper or a compatible local transcription implementation when a transcript is not supplied.
* Yaml files for templates and configuration

External programs such as FFmpeg should be invoked as subprocesses.

Do not embed FFmpeg libraries.

Do not expose raw FFmpeg expressions in the persistent project/edit formats.

---

# 3. Initial Workflow

The simplest workflow should be:

```text
source.mp4
    |
    v
inspect source
    |
    v
transcribe
    |
    v
analyze transcript/audio
    |
    v
generate edit plan
    |
    v
render
    |
    v
output.mp4
```

The user should eventually be able to perform this with approximately:

```bash
vidpp process source.mp4
```

or:

```bash
vidpp process source.mp4 --template templates/default.yaml
```

The command should create a project directory containing all intermediate data and the final output.

Individual stages must also be executable independently.

For example:

```bash
vidpp import source.mp4 project/
vidpp transcribe project/
vidpp analyze project/
vidpp plan project/
vidpp render project/
```

Also provide:

```bash
vidpp process ...
```

as the convenient all-in-one command.

---

# 4. Input

The minimum required input is:

```text
source video
```

For example:

```text
video.mp4
video.mov
```

Optional inputs are:

* existing timestamped transcript;
* rendering template;
* background/frame image;
* subtitle style;
* hook text;
* hook bubble/background image;
* additional image/icon assets.

The source file must never be modified.

---

# 5. Project Structure

Create a project directory similar to:

```text
project/
├── project.json
├── source/
│   └── source.mp4
├── transcript.json
├── analysis.json
├── edit.json
├── assets/
├── cache/
├── previews/
└── output/
    └── final.mp4
```

`project.json` stores the project-specific hook as an optional top-level string:

```json
{
  "version": 1,
  "source_path": "/absolute/path/to/source.mp4",
  "hook": "Why privacy matters"
}
```

Supplying `--hook` while processing or operating on a project updates this
field. Render and preview use the saved value when `--hook` is omitted. An
explicit CLI hook has highest precedence, followed by the saved project hook,
then `hook.text` from the visual template. An explicit empty string clears the
saved hook and disables it.

Avoid unnecessary copies of large video files.

If practical, allow the project to reference the original source file rather than copying it.

All generated data should be reproducible or clearly identified as cache.

---

# 6. Template

Support a simple YAML configuration describing the presentation.

Example:

```yaml
version: 1

output:
  width: 1080
  height: 1920
  fps: source

video:
  fit: contain
  background: assets/background.png

subtitles:
  enabled: true
  font: "Noto Sans"
  weight: 600
  color: "#F8F8F8"
  outline_color: "#101010"
  outline_width: 3
  background: none
  position: bottom
  bottom_margin: 180
  max_lines: 2

hook:
  enabled: true
  text: "Why your private messages may not be private"
  font: "Noto Sans"
  weight: 700
  color: "#FFFFFF"
  background_color: "#D90F0F0F"
  corner_radius: 24
  padding_x: 32
  padding_y: 18
  duration: 4.0
  position: top

audio:
  normalize: true

editing:
  remove_false_starts: true
  remove_repetitions: true
  shorten_long_pauses: true
  long_pause_threshold: 1.5
  target_pause: 0.4
```

Not every property must be implemented immediately, but the design should accommodate them.

Validate templates and produce useful error messages.

---

# 7. Background / Frame

Allow an optional PNG, JPEG, SVG or similar supported asset to define the visual background/frame.

For vertical social-media output, the source camera image may not naturally fill the output frame.

For example:

```text
┌─────────────────────────┐
│       HOOK TEXT         │
│                         │
│   ┌─────────────────┐   │
│   │                 │   │
│   │   SOURCE VIDEO  │   │
│   │                 │   │
│   └─────────────────┘   │
│                         │
│      SUBTITLE TEXT      │
└─────────────────────────┘
```

The template should eventually be able to describe the source-video rectangle independently from the output dimensions.

For example:

```yaml
video:
  x: 40
  y: 280
  width: 1000
  height: 1100
  fit: cover
```

The renderer should perform the required scale/crop/pad operations.

---

# 8. Hook

Support an optional introductory hook.

The user supplies hook text and may optionally supply an SVG/PNG bubble or
background. Without an image, the renderer must measure the text and generate a
tightly sized rounded bubble. The default hook uses Noto Sans Bold, near-white
text, and an approximately 85% opaque dark background. It must be visually
larger and distinct from transcript subtitles.

```text
hook text
+
optional SVG/PNG bubble/background
```

For example:

```bash
vidpp process source.mp4 \
    --template tiktok.yaml \
    --hook "Why end-to-end encryption matters"
```

The hook should appear for a configurable duration near the beginning of the video.
Its font, weight, font size, text color, background color, corner radius, and
horizontal/vertical padding must be independently configurable. Eight-digit
template colors use opacity-first `#AARRGGBB` notation.

The bubble/background image should be independently configurable from the text so the same asset can be reused for many videos.

Do not rasterize SVG assets permanently merely because FFmpeg requires a rasterized intermediate representation. Cache generated representations when necessary.

---

# 9. Transcription

If the user supplies a timestamped transcript, use it.

Otherwise generate one locally.

The internal transcript representation should contain at least:

```json
{
  "segments": [
    {
      "start": 12.31,
      "end": 15.42,
      "text": "The server never receives the plaintext."
    }
  ]
}
```

Prefer word-level timestamps when the transcription engine supports them.

Preserve the original transcription separately from later corrected/display text.

---

# 10. Subtitle Generation

Generate burned-in subtitles.

The subtitle renderer must support at least:

* font;
* font weight;
* font size;
* text color;
* outline/shadow;
* optional background color, disabled by default;
* position;
* margins;
* maximum lines.

The default vertical-video style uses centered Noto Sans SemiBold, near-white
text, a strong near-black outline, no subtitle box, no more than two lines, and
a generous bottom safe margin. Visual defaults are specified against a
1080×1920 reference frame and scale proportionally with output dimensions;
explicit template dimensions remain output pixels.

Subtitle text should be broken into readable chunks rather than displaying entire transcript segments.

Aim for short social-media-style caption units.

The exact caption segmentation algorithm should be isolated behind an interface so it can be improved later.

Do not alter the semantic meaning of spoken text merely to make captions shorter.

---

# 11. Analysis

Perform deterministic analysis before asking the LLM for editorial decisions.

Useful observations include:

* silence ranges;
* silence duration;
* transcript segments;
* word timestamps;
* audio duration;
* source dimensions;
* frame rate;
* scene changes where useful;
* audio levels where useful.

Store results in:

```text
analysis.json
```

The LLM should receive structured observations rather than being expected to discover everything itself.

---

# 12. LLM Editing Agent

The LLM is an editorial decision-maker.

It must NOT:

* construct arbitrary shell commands;
* execute FFmpeg;
* write arbitrary files;
* generate FFmpeg filter graphs;
* directly modify source media.

It receives compact, numbered transcript windows with gap durations and produces semantic edit candidates. Exact source timestamps are not sent to or accepted from the model.

For a normal-length recording, use explicit stages:

1. inspect the opening for abandoned starts;
2. slide bounded windows through the middle to find repeated takes, restarts, and clearly superseded fragments;
3. inspect the ending for an abandoned tail or repeated conclusion.

Each window has an exclusive ownership range plus overlapping read-only context. Accept only candidates whose first speech block belongs to that window's ownership range. This provides complete coverage without letting overlapping windows own the same decision. Keep the format compact, for example `[speech_id, text, gap_after_seconds]`, and retain every numbered request and response for debugging.

The model returns inclusive speech-block IDs and a short reason. Deterministic code assigns operation IDs, maps the private block IDs to timestamps, deduplicates exact candidates, and validates the result before writing the persistent edit plan.

For example:

```json
{
  "operations": [
    {
      "start": 4,
      "end": 6,
      "reason": "speaker abandons sentence and restarts it"
    }
  ]
}
```

Validate all LLM output against a strict schema.

Reject malformed or impossible operations.

---

# 13. Editing Policy

The default editing policy should be conservative.

Use instructions equivalent to:

```text
Never change the meaning of speech.

Prefer KEEP when uncertain.

Remove an abandoned sentence when the speaker clearly
restarts and replaces it.

Remove a repeated explanation only when the later version
clearly supersedes the earlier one.

Do not remove repetition used intentionally for emphasis.

Preserve natural conversational pauses.

Shorten unusually long unintended pauses instead of
removing all silence.

Do not make speech sound unnaturally continuous.

Never invent spoken content.

When uncertain, mark an edit for review rather than
performing an aggressive edit.
```

Keep this policy in a separate prompt/configuration file so it can easily be modified.

---

# 14. Edit Plan

Store the proposed edit in:

```text
edit.json
```

This is a semantic description of the resulting timeline.

It must not contain FFmpeg implementation details.

Each editorial operation should have a stable ID.

For example:

```json
{
  "version": 1,
  "operations": [
    {
      "id": "edit-0017",
      "type": "remove",
      "source_start": 31.2,
      "source_end": 39.8,
      "enabled": true,
      "reason": "false start"
    }
  ]
}
```

The user must be able to disable an operation without regenerating the complete plan.

This becomes important when a GUI is added.

---

# 15. Renderer

The renderer converts:

```text
source
+
edit.json
+
transcript
+
template
+
assets
```

into the final video.

Rendering must be deterministic.

The renderer is responsible for converting semantic operations into FFmpeg operations.

It should handle:

* cuts;
* pause shortening;
* scaling;
* cropping;
* background/frame composition;
* subtitles;
* hook;
* audio normalization;
* final encoding.

Keep command generation isolated and testable.

Print or log generated FFmpeg commands when verbose/debug logging is enabled.

---

# 16. Preview

Support fast preview rendering.

For example:

```bash
vidpp preview project/
```

Preview rendering may use:

* reduced resolution;
* faster codec settings;
* lower bitrate.

The purpose is rapid review of editing decisions rather than distribution quality.

Also support rendering a selected range eventually:

```bash
vidpp preview project/ --start 30 --end 60
```

---

# 17. Final Rendering

A command such as:

```bash
vidpp render project/ --final
```

should produce the distribution-quality output.

Initial target:

```text
MP4
H.264
AAC
1080x1920
```

unless overridden by the template.

Preserve sensible source frame rate unless explicitly configured otherwise.

Use broadly compatible encoding parameters appropriate for social-media uploads.

---

# 18. Safety and Validation

Treat all generated LLM data as untrusted.

Validate:

* timestamps;
* operation types;
* ranges;
* filenames;
* asset paths;
* dimensions;
* durations;
* numeric bounds;
* template values.

The LLM must never be able to inject command-line arguments or shell expressions into FFmpeg execution.

Use subprocess argument arrays rather than constructing shell command strings.

Do not invoke subprocesses through a shell unless absolutely unavoidable.

Do not allow project-relative paths to escape the project or explicitly configured asset directories.

---

# 19. Logging

Provide useful CLI logging.

Normal mode should show high-level progress:

```text
Inspecting source...
Transcribing...
Analyzing audio...
Planning edits...
12 proposed edits.
Rendering preview...
Done: previews/preview.mp4
```

Verbose mode should expose technical details.

For example:

```bash
vidpp -v ...
vidpp -vv ...
```

---

# 20. Tests

Add automated tests for at least:

* template parsing;
* project parsing;
* edit-plan validation;
* timestamp validation;
* overlapping edits;
* subtitle segmentation;
* FFmpeg command generation;
* malicious/invalid LLM output;
* unsafe paths;
* missing assets.

Where practical, generate tiny synthetic video/audio fixtures with FFmpeg rather than storing large media files in the repository.

Integration tests should render very short videos and verify that FFmpeg succeeds.

---

# 21. Architecture for Future GUI

Do not couple the processing engine to the CLI.

The architecture should approximately be:

```text
             Core
              |
     +--------+--------+
     |                 |
    CLI             future UI
                       |
                    Qt/QML
```

The eventual Qt/QML application should be able to display:

* source video;
* resulting preview;
* transcript;
* proposed cuts;
* enabled/disabled edits;
* subtitle styling;
* hook text;
* template selection;
* rendering progress.

Do not implement the GUI in the initial version.

---

# 22. Future Worker Interface

Design the processing engine so it can later run as a separate worker process.

A future interface could use JSON messages over stdin/stdout:

```json
{"command":"analyze","project":"..."}
```

with responses such as:

```json
{"event":"progress","stage":"analyze","value":0.37}
```

and:

```json
{"event":"complete","stage":"analyze"}
```

Do not spend significant effort implementing this protocol yet. Simply avoid architectural decisions that make it difficult.

---

# 23. Initial Milestone

The first milestone should intentionally be small.

Given:

```text
source.mp4
template.yaml
background.png
hook.svg
```

and:

```bash
vidpp process source.mp4 \
    --template template.yaml \
    --hook "Why privacy matters"
```

the program should:

1. inspect the video;
2. create a project;
3. transcribe speech locally;
4. detect long silences;
5. ask the configured local LLM to identify obvious false starts and repetitions;
6. validate and save `edit.json`;
7. render the edited video;
8. place the video into the configured background/frame;
9. display the hook using the supplied hook graphic;
10. render readable subtitles using the configured font/style;
11. normalize audio;
12. produce `output/final.mp4`.

The resulting project must retain enough intermediate information that individual decisions can be inspected and the video can be rerendered without rerunning transcription or the LLM.

---

# 24. Implementation Order

Implement incrementally.

**Phase 1 — deterministic renderer**

Implement:

```text
import
template parsing
ffprobe
project format
background/frame
source positioning
hook
subtitles from supplied transcript
FFmpeg rendering
```

This phase should require no LLM.

**Phase 2 — transcription**

Add local transcription and subtitle generation.

**Phase 3 — mechanical editing**

Add:

```text
silence detection
pause shortening
edit.json
timeline reconstruction
```

**Phase 4 — local LLM**

Add the model interface and conservative editorial planning for:

```text
false starts
repeated takes
obvious verbal mistakes
```

**Phase 5 — review workflow**

Add:

```text
preview
edit enable/disable
rerender
diagnostics
```

Do not start with an autonomous agent framework. A simple, explicit pipeline with one well-defined LLM decision stage is preferable.

---

# 25. Non-Goals for the Initial Version

Do not initially implement:

* arbitrary multi-track editing;
* general-purpose timeline editing;
* multiple camera synchronization;
* automatic B-roll generation;
* generative video;
* arbitrary transitions;
* complex animations;
* cloud services;
* publishing directly to TikTok/YouTube/etc.;
* social-media account management;
* Qt GUI;
* plugin architecture;
* model fine-tuning.

These can be considered after the basic workflow has proven useful.

---

# 26. Design Principle

Keep intelligence and execution separate.

The architecture should follow:

```text
deterministic analysis
        |
        v
structured observations
        |
        v
small local LLM
        |
        v
semantic edit.json
        |
        v
strict validation
        |
        v
deterministic FFmpeg renderer
```

The LLM decides *what would make a better edit*.

Normal software decides *exactly how that edit is performed*.

This separation is important for reliability, security, reproducibility, debugging, future GUI support, and the ability to replace either the model or rendering backend independently.
