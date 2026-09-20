# AGENTS.md

## Project

VidPP is a privacy-first, local video post-processing tool. See `README.md` and the project specification for goals and architecture.

## Principles

* Local processing is the default. Do not introduce cloud services or upload media, transcripts, frames, or metadata without an explicit requirement.
* Never modify source media.
* Keep AI decisions separate from execution: models produce validated semantic edit plans; deterministic code performs edits.
* Treat all model output as untrusted input and validate it strictly.
* Prefer simple, explicit pipelines over autonomous agent frameworks.
* Keep the core independent of the CLI so a Qt/QML frontend can be added later.
* Use FFmpeg/ffprobe for media processing rather than reimplementing codecs or media operations.
* Do not expose FFmpeg commands/filter graphs in persistent project formats.
* Avoid unnecessary dependencies and abstractions.

## Development

* Python 3.12+.
* Add tests for new behavior and bug fixes where practical.
* Use small generated media fixtures for integration tests.
* Never invoke subprocesses through a shell when an argument array will work.
* Preserve inspectable intermediate artifacts when useful for debugging.
* Keep changes focused; do not refactor unrelated code.
* During development testing, models will run on another machine. Use environment variables to access them. Document the expected environment variables and their corresponding CLI commands on the model machine. During normal use, models will run locally and must be started and discarded as needed.
* Use best practices: simple, modern code that is understandable and correct.
* Don't make assumptions about my preferences. Always ask when in doubt.
* Be generous with logging at debug and trace levels. Debug level should show me exactly what decisions are made, including transcript blocks, timestamps, and all commands executed. Trace level is for debugging and must contain all context required to investigate an issue.
