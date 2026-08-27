"""Découpage de la transcription en blocs pour l'analyse.

Le découpage se fait sur des frontières de segments, jamais au milieu d'un
segment : un horodatage reste ainsi toujours associé à un texte complet.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..models import TranscriptSegment


@dataclass(frozen=True)
class Chunk:
    """Bloc de transcription prêt à être analysé."""

    number: int
    text: str
    start_timestamp: str
    end_timestamp: str
    segment_count: int


def chunk_segments(
    segments: Sequence[TranscriptSegment],
    max_characters: int = 12000,
    overlap_segments: int = 2,
) -> list[Chunk]:
    """Découpe les segments en blocs d'au plus ``max_characters`` caractères.

    Un recouvrement de quelques segments entre blocs consécutifs évite de couper
    une idée en deux et de perdre le point clé qui s'y trouvait.
    """
    if max_characters < 500:
        raise ValueError("max_characters doit valoir au moins 500")
    if not segments:
        return []

    lines = [f"[{s.timestamp}] {s.text}" for s in segments]
    chunks: list[Chunk] = []
    start_index = 0
    number = 1

    while start_index < len(segments):
        size = 0
        end_index = start_index
        while end_index < len(segments):
            line_length = len(lines[end_index]) + 1
            if size and size + line_length > max_characters:
                break
            size += line_length
            end_index += 1
        if end_index == start_index:  # segment unique plus long que la limite
            end_index = start_index + 1

        window = segments[start_index:end_index]
        chunks.append(
            Chunk(
                number=number,
                text="\n".join(lines[start_index:end_index]),
                start_timestamp=window[0].timestamp,
                end_timestamp=window[-1].timestamp,
                segment_count=len(window),
            )
        )
        number += 1
        if end_index >= len(segments):
            break
        start_index = max(end_index - overlap_segments, start_index + 1)

    return chunks
