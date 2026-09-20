"""Word-based caption grouping with font-measured line wrapping."""
from dataclasses import replace
import logging
import subprocess

try:
    from PIL import ImageFont
except ModuleNotFoundError:  # Existing editable installs may predate this dependency.
    ImageFont = None

from .errors import VidPPError
from .models import TranscriptSegment, TranscriptWord

LOG = logging.getLogger(__name__)


def timed_words(segment: TranscriptSegment) -> tuple[TranscriptWord, ...]:
    if segment.words:
        return segment.words
    # Legacy supplied transcripts remain usable, but cannot provide exact timing.
    LOG.warning("No word timestamps for %.3f–%.3f; estimating caption timing. Retranscribe for speech alignment.", segment.start, segment.end)
    words = segment.text.split()
    total = sum(len(word) for word in words)
    elapsed = 0
    result = []
    for word in words:
        start = segment.start + (segment.end - segment.start) * elapsed / total
        elapsed += len(word)
        end = segment.start + (segment.end - segment.start) * elapsed / total
        result.append(TranscriptWord(start, end, word))
    return tuple(result)


def caption_font(name: str, size: int):
    if ImageFont is None:
        raise VidPPError(
            "Pillow is required for subtitle layout. Update the active virtual environment with "
            "'python -m pip install -e .', then retry."
        )
    try:
        LOG.debug("Resolving subtitle font: fc-match -f %%{file} %r", name)
        result = subprocess.run(["fc-match", "-f", "%{file}", name], capture_output=True, text=True, check=True)
        font = ImageFont.truetype(result.stdout.strip(), size)
        LOG.debug("Subtitle font resolved to %s at %d pixels", result.stdout.strip(), size)
        return font
    except (OSError, subprocess.CalledProcessError) as exc:
        raise VidPPError("Cannot resolve subtitle font; install fontconfig and the configured font") from exc


def caption_chunks(
    segments: list[TranscriptSegment],
    max_lines: int = 2,
    *,
    font=None,
    width: int = 920,
    max_words: int = 12,
    pause_threshold: float = 0.45,
    max_duration: float = 3.5,
    linger: float = 1.0,
) -> list[TranscriptSegment]:
    """Group timed words into readable phrases and measured lines."""
    words = [word for segment in segments for word in timed_words(segment)]
    raw_result = []
    current = []

    def wrap(items):
        lines = [""]
        for item in items:
            text = item.word.strip()
            candidate = (lines[-1] + " " + text).strip()
            length = font.getlength(candidate) if font else len(candidate) * 27
            if lines[-1] and length > width:
                lines.append(text)
            else:
                lines[-1] = candidate
            if font and font.getlength(text) > width:
                raise VidPPError(f"Subtitle word {text!r} does not fit; reduce subtitles.font_size")
        return lines

    def flush():
        if current:
            text = "\n".join(wrap(current))
            raw_result.append(TranscriptSegment(current[0].start, max(current[-1].end, current[0].start + .01), text, tuple(current)))
            current.clear()

    for word in words:
        candidate = [*current, word]
        if current and (
            word.start - current[-1].end > pause_threshold
            or word.end - current[0].start > max_duration
            or len(candidate) > max_words
            or len(wrap(candidate)) > max_lines
        ):
            flush()
        current.append(word)
        # Spoken sentence and clause boundaries are preferable to arbitrary size cuts.
        if word.word.rstrip().endswith((".", "?", "!", ",", ";", ":")):
            flush()
    flush()

    result = []
    timeline_end = max((segment.end for segment in segments), default=0.0)
    for index, caption in enumerate(raw_result):
        next_start = raw_result[index + 1].start if index + 1 < len(raw_result) else timeline_end
        # Extend only when speech was faster than a comfortable three words/second,
        # never past the next caption and never more than the configured linger.
        reading_end = caption.start + len(caption.words) / 3.0
        end = min(max(caption.end, reading_end), caption.end + linger, next_start, timeline_end)
        caption = replace(caption, end=max(caption.end, end))
        result.append(caption)
        LOG.debug("Caption %.3f–%.3f: %s", caption.start, caption.end, caption.text)
    return result


def remap_transcript(transcript: list[TranscriptSegment], ranges: list[tuple[float, float]]) -> list[TranscriptSegment]:
    result = []
    output_start = 0.0
    for start, end in ranges:
        for segment in transcript:
            if segment.end <= start or segment.start >= end:
                continue
            if not segment.words and (segment.start < start - .01 or segment.end > end + .01):
                raise VidPPError("An edit crosses a segment without word timestamps. Retranscribe or disable the edit.")
            words = timed_words(segment)
            retained = []
            for word in words:
                if word.end <= start or word.start >= end:
                    continue
                if word.start < start - .02 or word.end > end + .02:
                    raise VidPPError(f"Edit cuts through spoken word {word.word!r} at {word.start:.3f}–{word.end:.3f}; adjust its boundaries")
                retained.append(replace(word, start=output_start + max(word.start, start) - start,
                                        end=output_start + min(word.end, end) - start))
            if retained:
                result.append(TranscriptSegment(retained[0].start, retained[-1].end,
                                                " ".join(w.word.strip() for w in retained), tuple(retained)))
        output_start += end - start
    return result
