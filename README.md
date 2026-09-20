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

Multiple inputs are normalized and concatenated into `cache/master.mp4`. Transcription, analysis, semantic edits, captions, and rendering use that continuous master timeline. The original videos are only read. `project.json` retains every original absolute path, its inspected metadata, and its start/end on the master timeline. If the cached master is deleted, VidPP rebuilds it from the originals.

For now, inputs must have matching displayed dimensions and frame rates and must contain audio. VidPP validates dimensions and frame rate before combining them; FFmpeg reports other incompatible stream details. A single source continues to be referenced directly without creating a master. Without `--project`, a multi-source project is named after the first input.

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

The renderer needs local `ffmpeg`/`ffprobe` with libass and an installed subtitle font. It renders H.264/AAC MP4, edits detected long silences conservatively, composes an optional background and hook image, burns captions, and normalizes audio.

### Local transcription and editorial model

For local use, VidPP transcribes with the local `whisper` executable when no `--transcript` is supplied. Install it only inside the active virtual environment:

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
  model: turbo
  recovery_model: turbo
  language: en
  phrases:
    - VidPP
    - OneRSS
    - end-to-end encryption
```

Project model/language settings override global settings; `VIDPP_WHISPER_MODEL`, `VIDPP_WHISPER_RECOVERY_MODEL`, and `VIDPP_WHISPER_LANGUAGE` override them. Phrase lists are combined in global-then-project order, normalized for Unicode and whitespace, and deduplicated case-insensitively while keeping the first spelling. The combined vocabulary is passed to Whisper as `--initial_prompt`. Keep it focused: Whisper has a limited prompt context and vocabulary hints cannot force a recognition. The effective settings are saved in `cache/transcription-settings.json` and logged at debug level. Whisper documents this prompt as useful for names and vocabulary in its [transcription implementation](https://github.com/openai/whisper/blob/main/whisper/transcribe.py).

For a new project, supply its configuration before transcription:

```bash
vidpp process source.mp4 --project-config recording-config.yaml
# Or set up stages separately:
vidpp import source.mp4 project/ --project-config recording-config.yaml
vidpp transcribe project/
```

The supplied configuration is copied to `project/config.yaml`. For an existing project, edit that file and rerun `vidpp transcribe project/`. VidPP detects suspicious alignment—leading untranscribed audio, words stretched beyond two seconds, or unexplained word gaps—and runs a context-independent Whisper recovery pass only over those regions. A region is replaced only when recovery finds more words, so a weaker second pass cannot silently discard primary text. The raw primary and recovery results remain in `cache/` and `cache/recovery/`; reconciliation details are in `cache/transcription-recovery.json`. By default the recovery pass uses the primary model. Set `recovery_model: large-v3` (or `VIDPP_WHISPER_RECOVERY_MODEL=large-v3`) for higher quality at the cost of a larger model and slower loading. Word timestamps and confidence are retained in `transcript.json`; deterministic sentence grouping is written to `cache/sentences.json`.

### Captions and reviewing edits

Captions use actual word boundaries and font-measured line breaks. Sentence endings, commas, semicolons and colons are preferred boundaries. Long phrases split by word count, duration, available lines, or a pause. A caption may linger for reading, but only for a bounded time and never across the next spoken phrase; the remainder of a long pause has no caption. These controls belong in the visual template:

```yaml
subtitles:
  max_lines: 2
  font_size: 54
  max_words: 8
  max_characters: 48
  max_duration: 3.5
  pause_threshold: 0.45
  linger: 1.0
```

`max_characters` counts letters and punctuation but not spaces or inserted line breaks. A single word is never split merely to satisfy that limit. Durations are seconds. Font lookup requires `fontconfig` (`sudo apt-get install fontconfig` on Debian/Ubuntu). The default font size is 54 pixels at p720 and scales with the output's short edge; an explicit `subtitles.font_size` is always in output pixels. Sentence grouping and short caption grouping are separate operations. Install updated dependencies in your active venv with `python -m pip install -e .`.

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
  --ctx-size 16384 --n-predict 1024
```

`--n-gpu-layers all` asks llama.cpp to place all layers that fit in VRAM; reduce it to a number if the model does not fit. Confirm the startup log identifies `ggml_vulkan` and the AMD device. Point VidPP at the server alias:

```bash
export VIDPP_LLM_BASE_URL=http://127.0.0.1:8080/v1
export VIDPP_LLM_MODEL=vidpp-editor
```

For a model server on another trusted machine, replace `127.0.0.1` in `--host` and `VIDPP_LLM_BASE_URL` with its private-network address, set `--api-key` on `llama-server`, and export the same value as `VIDPP_LLM_API_KEY` for VidPP. Do not expose the server directly to the public internet; use a firewall and reverse proxy if that is unavoidable.

The model receives structured transcript and silence observations and can only return schema-validated semantic operations; it cannot run commands or construct FFmpeg filters. Without these variables VidPP still produces a deterministic pause-edit plan.

VidPP sends the editorial model a compact numbered timeline instead of duplicating Whisper's segment, word, sentence, and timestamp representations. Speech entries contain text; silence entries contain only their duration in seconds so the model can understand pacing. Silence detections that overlap recognized speech are excluded. The model selects 1-based integer speech-block numbers; deterministic Python code keeps the private index that converts those numbers to exact timestamps, so floating-point rounding cannot create an unsafe boundary. The complete request and raw server response are retained as `cache/editorial-request.json` and `cache/editorial-response.json` for debugging. `VIDPP_LLM_TIMEOUT` controls the HTTP wait in seconds (default `600`, valid range `1`–`86400`). While waiting, llama.cpp prints prompt-ingestion and generation progress in its server terminal; VidPP announces the selected model, block count, and timeout. If a request still times out, increase the timeout or use a smaller/faster instruct model.
