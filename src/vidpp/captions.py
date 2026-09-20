"""Word-based caption grouping with font-measured line wrapping."""
from dataclasses import replace
import logging
import subprocess

from PIL import ImageFont

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
    try:
        LOG.debug("Resolving subtitle font: fc-match -f %%{file} %r", name)
        result = subprocess.run(["fc-match", "-f", "%{file}", name], capture_output=True, text=True, check=True)
        font = ImageFont.truetype(result.stdout.strip(), size)
        LOG.debug("Subtitle font resolved to %s at %d pixels", result.stdout.strip(), size)
        return font
    except (OSError, subprocess.CalledProcessError) as exc:
        raise VidPPError("Cannot resolve subtitle font; install fontconfig and the configured font") from exc


def caption_chunks(segments: list[TranscriptSegment], max_lines: int = 2, *, font=None, width: int = 920) -> list[TranscriptSegment]:
    words = [word for segment in segments for word in timed_words(segment)]
    result = []
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
            result.append(TranscriptSegment(current[0].start, max(current[-1].end, current[0].start + .01), text, tuple(current)))
            LOG.debug("Caption %.3f–%.3f: %s", result[-1].start, result[-1].end, text)
            current.clear()

    for word in words:
        if current and (word.start - current[-1].end > .45 or word.end - current[0].start > 3.5 or len(wrap([*current, word])) > max_lines):
            flush()
        current.append(word)
        if word.word.rstrip().endswith((".", "?", "!", ";")):
            flush()
    flush()
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
