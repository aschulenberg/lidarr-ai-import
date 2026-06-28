from __future__ import annotations

from .ai.base import MatchCandidate

_MS_PER_SECOND = 1000.0


def track_duration_seconds(track: dict) -> float | None:
    duration_ms = track.get("duration")
    if not duration_ms:
        return None
    return round(duration_ms / _MS_PER_SECOND, 2)


def release_lookup(album: dict) -> dict[int, dict]:
    return {r["id"]: r for r in album.get("releases", []) if "id" in r}


def build_candidates(
    scored_tracks: list[tuple[dict, float]], albums_by_id: dict[int, dict]
) -> tuple[list[MatchCandidate], dict[int, tuple[dict, dict, dict]]]:
    """scored_tracks: (track, similarity) pairs, best-first - see matching.find_similar_tracks.
    Returns the candidate list to hand the AI plus a lookup back to the raw
    (track, release, album) dicts so the caller can act on whichever index it picks."""
    candidates: list[MatchCandidate] = []
    lookup: dict[int, tuple[dict, dict, dict]] = {}

    for index, (track, _score) in enumerate(scored_tracks):
        album = albums_by_id.get(track.get("albumId"))
        if not album:
            continue
        release = release_lookup(album).get(track.get("albumReleaseId"), {})
        candidate = MatchCandidate(
            index=index,
            album_id=album["id"],
            album_title=album.get("title", "?"),
            album_type=album.get("albumType", "Unknown"),
            release_id=release.get("id", track.get("albumReleaseId")),
            release_title=release.get("title", album.get("title", "?")),
            release_date=album.get("releaseDate"),
            track_id=track["id"],
            track_title=track.get("title", "?"),
            track_number=track.get("trackNumber"),
            disc_number=track.get("mediumNumber"),
            duration_seconds=track_duration_seconds(track),
        )
        candidates.append(candidate)
        lookup[index] = (track, release, album)

    return candidates, lookup
