from __future__ import annotations

import logging
import os
from typing import Any

from mutagen import File as MutagenFile

log = logging.getLogger(__name__)


def read_audio_tags(path: str) -> dict[str, Any]:
    """Best-effort tag read. Returns an empty-ish dict on failure rather than raising -
    a corrupt or unreadable file shouldn't take down a batch resolve."""
    info: dict[str, Any] = {
        "path": path,
        "filename": os.path.basename(path),
        "title": None,
        "artist": None,
        "album": None,
        "track_number": None,
        "disc_number": None,
        "duration_seconds": None,
        "bitrate": None,
        "musicbrainz_track_id": None,
        "musicbrainz_release_id": None,
    }
    try:
        audio = MutagenFile(path, easy=True)
        if audio is None:
            return info
        tags = audio.tags or {}

        def first(key: str) -> str | None:
            value = tags.get(key)
            return value[0] if value else None

        info["title"] = first("title")
        info["artist"] = first("artist")
        info["album"] = first("album")
        info["track_number"] = first("tracknumber")
        info["disc_number"] = first("discnumber")
        info["musicbrainz_track_id"] = first("musicbrainz_trackid")
        info["musicbrainz_release_id"] = first("musicbrainz_albumid")

        if getattr(audio, "info", None) is not None:
            info["duration_seconds"] = round(getattr(audio.info, "length", 0) or 0, 2)
            info["bitrate"] = getattr(audio.info, "bitrate", None)
    except Exception as exc:
        log.warning("Failed to read tags from %s: %s", path, exc)
    return info
