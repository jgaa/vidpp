# VidPP

VidPP is a local video post-processing tool for turning simple recordings into videos ready for social media.

I want to be able to record a video on my phone or a camera without spending a lot of time trying to make every take perfect. VidPP should take care of the boring post-processing: remove false starts, unnecessary repetitions and long unplanned pauses, clean up the presentation, generate subtitles, and render the result using a consistent visual style.

For simple videos, I should only have to provide the source video and, optionally, a template describing how the result should look. The template can define things like a background or frame around the video, subtitle font, size and color, and a PNG or SVG bubble for displaying the hook text. The same template should be reusable across many productions so that the videos have a consistent appearance without having to manually recreate the layout every time.

**Privacy and local processing are important goals of VidPP.** Source videos may contain material that I do not want to upload to third-party services just to edit them. Video, audio, transcription, analysis, AI-assisted editing and rendering should therefore be performed locally whenever possible. The normal workflow should not require sending the source material, transcript or extracted frames to a cloud service. Local models should be sufficient for the routine AI tasks, while the architecture should not prevent explicitly using a remote model when I choose to do so.

VidPP uses existing tools such as FFmpeg for the actual media processing. Where editorial decisions are needed, a small local language model can analyze the transcript and suggest what should be removed or shortened. The model decides *what* to edit; deterministic code decides *how* to perform the edit. The original recording is never modified.

The initial version of VidPP will be a CLI application. The internal project and edit formats should be clean and independent of the CLI so that a proper GUI can be added later. The goal is not to build another general-purpose video editor. The goal is to automate as much as possible of the repetitive work between recording a simple video and having something ready to publish.

## MVP usage

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
vidpp process source.mp4 --transcript transcript.json --template template.yaml --hook "Why privacy matters"
```

The effective hook is saved as `hook` in `project.json`. Later renders therefore
do not need it repeated:

```bash
vidpp render source.vidpp
```

An explicit `--hook` updates the saved project value. Use `--hook ""` to clear
it. Hook precedence is an explicit CLI value, then the saved project hook, then
the template's `hook.text`.

Pass `--open` to `process` or `render` to launch the completed video in the
operating system's default viewer without waiting for the viewer to close:

```bash
vidpp process source.mp4 --open
vidpp render source.vidpp --open
```

On Linux this uses `xdg-open`; on macOS it uses `open`; on Windows it uses the
registered file association.

For a source that is already edited, keep the full timeline and run only transcription, subtitles, template processing, audio processing, and rendering:

```bash
vidpp process source.mp4 --no-edit
```

`--no-edit` skips audio edit analysis and editorial-model planning during `process`. It is also accepted by `render` and `preview`, where it explicitly ignores any stored `edit.json` operations:

```bash
vidpp render project.vidpp --no-edit
vidpp preview project.vidpp --no-edit
```

All Python packages are installed in `.venv`; the machine's shared Python environment is not changed. On Debian/Ubuntu, install the matching `python3-venv` package first if `python3 -m venv` reports that `ensurepip` is unavailable. To run tests, use `python -m pip install pytest` and then `python -m pytest` while the environment is active.

`transcript.json` contains timestamped segments, for example `{"segments":[{"start":0.0,"end":2.2,"text":"A short spoken sentence."}]}`. VidPP creates `source.vidpp/` by default, references rather than copies the source, retains the transcript, analysis and semantic edit plan, and writes `output/final.mp4`. Individual stages are `import`, `transcribe`, `analyze`, `plan`, `preview`, and `render`.

### Multiple source videos

Pass source videos in the order they should appear:

```bash
vidpp process take-1.mp4 take-2.mp4 take-3.mp4 \
  --project combined.vidpp \
  --hook "One continuous video"
```

For staged processing:

```bash
vidpp import take-1.mp4 take-2.mp4 take-3.mp4 combined.vidpp
vidpp transcribe combined.vidpp
vidpp analyze combined.vidpp
vidpp plan combined.vidpp
vidpp render combined.vidpp
```

Multiple inputs are normalized and concatenated into `cache/master.mp4`. Transcription, analysis, semantic edits, captions, and rendering use that continuous master timeline. The original videos are only read. `project.json` retains the project hook, every original absolute path, its inspected metadata, and its start/end on the master timeline. If the cached master is deleted, VidPP rebuilds it from the originals.

Use `--project-name` when only a local project name is needed; VidPP appends `.vidpp`. Use `--project` for an explicit destination path. `--replace-project` removes an existing destination before recreating it:

```bash
vidpp process source.mp4 --project-name fresh-take --replace-project
vidpp import first.mp4 second.mp4 combined.vidpp --replace-project
```

Replacement is destructive for the destination project directory. VidPP refuses symlinks, protected or broad directories, unrecognized non-`.vidpp` directories, and any destination containing one of the source files. Source media is never removed.

For now, inputs must have matching displayed dimensions, compatible nominal frame rates, and audio. VidPP compares frame rates numerically with a 5% tolerance because phone recordings commonly report slightly different average-rate fractions for the same nominal mode; genuinely different rates such as 24 fps and 30 fps remain incompatible. FFmpeg reports other incompatible stream details. A single source continues to be referenced directly without creating a master. Without `--project`, a multi-source project is named after the first input.

### Output size and orientation

The default destination is `p720` with automatic orientation. A landscape source produces 1280×720; a portrait source produces 720×1280. Auto treats a square source as landscape. The `p` value is the short edge of a 16:9 output and may be overridden for the complete pipeline or an individual render:

```bash
vidpp process source.mp4 --format p1080
vidpp render project/ --format p720 --orientation portrait
```

Valid orientations are `auto`, `portrait`, and `landscape`. A template can set the same values:

```yaml
output:
  format: p1080
  orientation: auto
```

Explicit template `output.width` and `output.height` remain supported and take precedence when there is no CLI format/orientation override. Specify both dimensions together and do not combine them with `output.format`.

The renderer needs local `ffmpeg`/`ffprobe` with libass, `fontconfig`, and an installed subtitle font. The defaults use Noto Sans; on Debian/Ubuntu install it with `sudo apt-get install fonts-noto-core fontconfig`. It renders H.264/AAC MP4, edits detected long silences conservatively, composes an optional background and hook, burns captions, and normalizes audio.

### Local transcription and editorial model

For local use, VidPP uses the configured local transcription engine when no `--transcript` is supplied. OpenAI Whisper is the default. Install it only inside the active virtual environment:

```bash
python -m pip install openai-whisper
```

FFmpeg is also required. The default Whisper model is `turbo`, with word timestamps enabled. It offers a stronger transcription starting point than the previous `base` default, but does not guarantee recognition of every word. English is the default language and is passed explicitly, avoiding a separate language-detection step. Set `VIDPP_WHISPER_LANGUAGE=auto` to detect it, or use another language code. Set `VIDPP_WHISPER_MODEL=large-v3` to try the full model, or `small` for lower resource use. Model weights may be downloaded on first use; speech processing stays local. The Python Whisper runtime uses PyTorch; llama.cpp's Vulkan acceleration does not enable Vulkan for Python Whisper. See the [Whisper model comparison](https://github.com/openai/whisper#available-models-and-languages).

If Whisper is unavailable, VidPP prints install instructions and exits without rendering. Alternatives are a timestamped `--transcript`, or `VIDPP_TRANSCRIBE_COMMAND` pointing to a local executable that accepts the source-video path as its final argument and writes compatible transcript JSON to stdout. That adapter controls its own model/prompt settings. VidPP invokes it as an argument array, never through a shell.

### Transcription configuration and vocabulary

Global settings live in `$XDG_CONFIG_HOME/vidpp/config.yaml`, normally `~/.config/vidpp/config.yaml`. `VIDPP_CONFIG=/path/to/config.yaml` overrides that location. Each project can also contain `config.yaml`. Both accept this schema (see `config.example.yaml`):

```yaml
version: 1
transcription:
  engine: whisper
  model: turbo
  recovery_model: turbo
  crisper_backend: auto
  language: en
  phrases:
    - VidPP
    - OneRSS
    - end-to-end encryption
```

Project transcription settings override global settings; environment variables override both. `VIDPP_TRANSCRIBE_MODEL` selects the model for either engine. The older `VIDPP_WHISPER_MODEL`, plus `VIDPP_WHISPER_RECOVERY_MODEL` and `VIDPP_WHISPER_LANGUAGE`, remain supported. Phrase lists are combined in global-then-project order, normalized for Unicode and whitespace, and deduplicated case-insensitively while keeping the first spelling. The combined vocabulary is passed to Whisper as `--initial_prompt`. Keep it focused: Whisper has a limited prompt context and vocabulary hints cannot force a recognition. The effective settings are saved in `cache/transcription-settings.json` and logged at debug level. Whisper documents this prompt as useful for names and vocabulary in its [transcription implementation](https://github.com/openai/whisper/blob/main/whisper/transcribe.py).

For a new project, supply its configuration before transcription:

```bash
vidpp process source.mp4 --project-config recording-config.yaml
# Or set up stages separately:
vidpp import source.mp4 project/ --project-config recording-config.yaml
vidpp transcribe project/
```

The supplied configuration is copied to `project/config.yaml`. For an existing project, edit that file and rerun `vidpp transcribe project/`. VidPP detects suspicious alignment—leading untranscribed audio, words stretched beyond two seconds, or unexplained word gaps—and runs a context-independent Whisper recovery pass only over those regions. A region is replaced only when recovery finds more words, so a weaker second pass cannot silently discard primary text. The raw primary and recovery results remain in `cache/` and `cache/recovery/`; reconciliation details are in `cache/transcription-recovery.json`. By default the recovery pass uses the primary model. Set `recovery_model: large-v3` (or `VIDPP_WHISPER_RECOVERY_MODEL=large-v3`) for higher quality at the cost of a larger model and slower loading. Word timestamps and confidence are retained in `transcript.json`; deterministic sentence grouping is written to `cache/sentences.json`.

### CrisperWhisper transcription

[CrisperWhisper 2](https://github.com/nyrahealth/CrisperWhisper) can replace OpenAI Whisper for verbatim transcription. Its verbatim mode is designed to retain filler words, repetitions, stutters, and false starts, and VidPP requests word-level timestamps. The Transformers implementation is installed with VidPP's normal dependencies, but this engine is never selected implicitly.

After pulling a dependency update, refresh the active virtual environment:

```bash
python -m pip install -e .
```

Then configure it globally or in `project/config.yaml`:

```yaml
version: 1
transcription:
  engine: crisperwhisper
  model: large
  crisper_backend: transformers
  language: en
```

Valid CrisperWhisper 2 model shorthands include `large`, `turbo`, `medium`, and `small`. `VIDPP_TRANSCRIBE_ENGINE=crisperwhisper`, `VIDPP_TRANSCRIBE_MODEL=large`, and `VIDPP_CRISPER_BACKEND=transformers` provide environment overrides. VidPP extracts `cache/crisper-audio.wav` with FFmpeg before inference, so video-container support does not depend on Python audio decoders. The Transformers backend uses PyTorch: it can use an AMD GPU only with a compatible ROCm-enabled PyTorch installation, not through Vulkan, and otherwise runs on CPU. The alternative `ct2` backend's documented GPU path targets NVIDIA CUDA.

Important licensing: CrisperWhisper's inference code is MIT, but its standard model weights use a non-commercial research license. Pro weights require a commercial license. Verify that the selected model's terms fit the intended videos before enabling this backend. VidPP passes configured vocabulary phrases as hotwords only for a `_pro` model because the CrisperWhisper documentation warns that hotwords can degrade standard-model transcription.

### Captions and reviewing edits

Captions use actual word boundaries and font-measured line breaks. Sentence endings, commas, semicolons and colons are preferred boundaries. Long phrases split by word count, duration, available lines, or a pause. A caption may linger for reading, but only for a bounded time and never across the next spoken phrase; the remainder of a long pause has no caption. These controls belong in the visual template:

```yaml
subtitles:
  font: "Noto Sans"
  weight: 600
  color: "#F8F8F8"
  outline_color: "#101010"
  outline_width: 3
  background: none
  max_lines: 2
  max_words: 8
  max_characters: 48
  max_duration: 3.5
  pause_threshold: 0.45
  linger: 1.0

hook:
  font: "Noto Sans"
  weight: 700
  color: "#FFFFFF"
  background_color: "#D90F0F0F"
  corner_radius: 24
  padding_x: 32
  padding_y: 18
```

The default subtitle is centered near-white Noto Sans SemiBold with a strong dark outline, no box, at most two lines, and a generous bottom safe margin. A text hook uses a larger Noto Sans Bold face in a rounded, semi-opaque, text-sized dark bubble. VidPP writes that generated overlay to `cache/hook.png`; an explicit `hook.image` continues to replace the generated bubble.

The eight-digit color form is opacity-first `#AARRGGBB`, so `#D90F0F0F` is approximately 85% opaque dark gray. `subtitles.background` accepts `none`, `#RRGGBB`, or `#AARRGGBB`. All listed style properties can be overridden in a template.

`max_characters` counts letters and punctuation but not spaces or inserted line breaks. A single word is never split merely to satisfy that limit. Durations are seconds. Font lookup requires `fontconfig`. Visual defaults scale from a 1080×1920 reference frame: subtitle type is 81 px and hook type is 108 px at p1080 (54 px and 72 px at p720), with padding, corner radius, outline, and safe margin scaled appropriately. Explicit template dimensions such as `font_size`, `padding_x`, and `corner_radius` are output pixels and do not scale. Sentence grouping and short caption grouping are separate operations. Install updated dependencies in your active venv with `python -m pip install -e .`.

Normal CLI output announces source inspection, model loading/transcription, audio analysis, edit planning, and rendering before each stage starts. Use `-v` for transcript decisions and executed commands.

Legacy transcripts without words use estimated caption timing with a warning. Edits crossing such a segment, or cutting through a timestamped word, stop rendering with an actionable error. Retranscribe older projects for reliable alignment.

LLM proposals are now saved with `enabled: false` and require review before setting `enabled: true` in `edit.json`. Valid JSON does not guarantee sensible editorial reasoning. Existing plans are not silently changed; regenerate or disable old incorrect operations. After changing a transcript, regenerate and review its plan before rendering:

```bash
vidpp transcribe project/
vidpp analyze project/
vidpp plan project/
# Review edit.json; enable only justified cuts.
vidpp render project/
```

Pass the same `--template` to stages that use a visual/editing template.

Optional editorial analysis uses a local OpenAI-compatible server only when both variables are set:

```bash
export VIDPP_LLM_BASE_URL=http://model-machine:8000/v1
export VIDPP_LLM_MODEL=Qwen3-4B-Instruct
# Optional; local thinking models may need several minutes. Default: 600 seconds.
export VIDPP_LLM_TIMEOUT=600
# Optional generation budget. Default: 8192; thinking-only models may need more.
export VIDPP_LLM_MAX_TOKENS=8192
```

### llama.cpp server on an AMD Vulkan system

Use a separate, full llama.cpp checkout for the server rather than reusing the copy nested in another application's CMake build. This keeps its CMake cache, targets, and shared-library options independent of a Whisper-integrated application. On Debian/Ubuntu, the build prerequisites are:

```bash
sudo apt-get install build-essential cmake git libvulkan-dev glslc spirv-headers vulkan-tools
vulkaninfo
git clone https://github.com/ggml-org/llama.cpp.git
cd llama.cpp
git submodule update --init --recursive
cmake -S . -B build \
  -DGGML_VULKAN=ON \
  -DBUILD_SHARED_LIBS=ON \
  -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j "$(nproc)"
```

This is a full Git history checkout and builds the complete project, including the shared libraries and `build/bin/llama-server`. `vulkaninfo` should identify the AMD GPU through the installed Vulkan driver before building. Start the server with a GGUF instruct model whose metadata contains the appropriate chat template:

```bash
./build/bin/llama-server \
  --model /absolute/path/to/Qwen3-4B-Instruct-Q4_K_M.gguf \
  --alias vidpp-editor \
  --host 127.0.0.1 --port 8080 \
  --n-gpu-layers all \
  --ctx-size 16384 --n-predict 8192
```

`--n-gpu-layers all` asks llama.cpp to place all layers that fit in VRAM; reduce it to a number if the model does not fit. Confirm the startup log identifies `ggml_vulkan` and the AMD device. Point VidPP at the server alias:

```bash
export VIDPP_LLM_BASE_URL=http://127.0.0.1:8080/v1
export VIDPP_LLM_MODEL=vidpp-editor
```

VidPP requests schema-constrained JSON and supplies its own `max_tokens` value, controlled by `VIDPP_LLM_MAX_TOKENS`. Qwen3-4B-Instruct-2507 is normally the faster fit for this bounded editorial classification task. Qwen3-4B-Thinking-2507 is also supported, but it is a thinking-only model and may consume substantially more generation tokens before producing the JSON plan; do not try to disable thinking for that checkpoint. If it reaches the generation limit, increase `VIDPP_LLM_MAX_TOKENS` and the server's `--n-predict` value together.

For a model server on another trusted machine, replace `127.0.0.1` in `--host` and `VIDPP_LLM_BASE_URL` with its private-network address, set `--api-key` on `llama-server`, and export the same value as `VIDPP_LLM_API_KEY` for VidPP. Do not expose the server directly to the public internet; use a firewall and reverse proxy if that is unavoidable.

The model receives compact transcript windows with pacing observations and can only return schema-validated semantic operations; it cannot run commands or construct FFmpeg filters. Without these variables VidPP still produces a deterministic pause-edit plan.

VidPP assigns each speech block a private integer ID and sends rows as `[id,text]` or `[id,text,gap_after_seconds]`; exact timestamps remain in deterministic Python code. The first pass examines the opening for false starts, middle passes slide through exclusively owned regions with surrounding context to find retakes and superseded fragments, and a final pass checks the ending. Context overlap helps the model reason across boundaries, but a window may only propose a cut beginning in its owned region, preventing duplicate ownership. Odd opinions, informal speech, filler, and probable transcription errors are explicitly not treated as nonsense.

The model returns only inclusive speech-block boundaries and a short reason. VidPP assigns stable operation IDs, converts boundaries to exact timestamps, deduplicates exact matches, validates every field, and leaves all editorial proposals disabled for review. Window definitions are retained in `cache/editorial-windows.json`; each complete request and raw response is retained as `cache/editorial-request-NNN.json` and `cache/editorial-response-NNN.json`. The unnumbered request/response files point to the latest window for convenience. `VIDPP_LLM_TIMEOUT` applies to each window (default `600`, valid range `1`–`86400`). VidPP announces window progress while llama.cpp reports prompt and generation progress in its server terminal.
