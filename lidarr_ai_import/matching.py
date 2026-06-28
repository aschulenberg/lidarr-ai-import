from __future__ import annotations

import re
from difflib import SequenceMatcher

_PARENTHETICAL_RE = re.compile(r"[\(\[][^\)\]]*[\)\]]")
_TRAILING_VERSION_RE = re.compile(
    r"\s*-\s*(single|radio|album|remaster(ed)?|mono|stereo|live|demo|edit|version|mix)\b.*$",
    re.IGNORECASE,
)
_PUNCT_RE = re.compile(r"[^a-z0-9 ]+")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_title(title: str | None) -> str:
    """Strip the cosmetic differences that make the *same* song look like different
    strings across a single/EP/album release: parentheticals, "- Radio Edit" style
    suffixes, punctuation, case."""
    if not title:
        return ""
    value = title.lower()
    value = _PARENTHETICAL_RE.sub("", value)
    value = _TRAILING_VERSION_RE.sub("", value)
    value = _PUNCT_RE.sub("", value)
    value = _WHITESPACE_RE.sub(" ", value).strip()
    return value


def title_similarity(a: str | None, b: str | None) -> float:
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def duration_close(a: float | None, b: float | None, tolerance_seconds: float = 4.0) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= tolerance_seconds


def find_similar_tracks(
    target_title: str,
    candidate_tracks: list[dict],
    *,
    title_key: str = "title",
    threshold: float = 0.82,
) -> list[tuple[dict, float]]:
    """Returns (track, similarity) pairs above threshold, sorted best-first."""
    scored = []
    for track in candidate_tracks:
        score = title_similarity(target_title, track.get(title_key))
        if score >= threshold:
            scored.append((track, score))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored
