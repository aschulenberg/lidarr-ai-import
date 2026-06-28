from __future__ import annotations

import logging
from collections import defaultdict

from .ai.base import AIProvider
from .candidates import build_candidates, track_duration_seconds
from .config import Config
from .lidarr_client import LidarrClient
from .matching import find_similar_tracks
from .storage import DecisionStore

log = logging.getLogger(__name__)

_TASK_DESCRIPTION = """You are reviewing a track Lidarr considers "missing" for an artist, to see \
whether it is genuinely absent from the library or whether the library already contains the same \
recording filed under a different release. The same song is often released more than once for an \
artist - as a standalone Single, on an EP, and later on a full Album - each tracked by Lidarr as a \
separate release. A track can show up as "missing" under one of those releases while the listener \
already owns the identical recording under another. Decide whether one of the candidates (tracks \
this artist's library already has on disk) is the SAME recording as the missing target, just filed \
under a different release, rather than a genuinely distinct version."""

# This tool only ever reports on missing-vs-have mismatches; it never moves or
# re-associates an already-imported file. Re-routing a library file to a different
# track/release would need a verified-safe Lidarr API path we don't have confidence
# in yet, so that step is left for a human using Lidarr's own Manual Import UI.


class MissingReconciler:
    """Cross-references Lidarr's wanted/missing list against the rest of each artist's
    library to separate true gaps from "you already have this, it's just filed under a
    different single/EP/album release." Report-only - see module note above."""

    def __init__(self, lidarr: LidarrClient, ai: AIProvider, store: DecisionStore, config: Config):
        self.lidarr = lidarr
        self.ai = ai
        self.store = store
        self.config = config

    def run_once(self) -> list[dict]:
        missing_by_artist: dict[int, list[dict]] = defaultdict(list)
        for record in self.lidarr.iter_wanted_missing():
            artist_id = record.get("artistId")
            if artist_id:
                missing_by_artist[artist_id].append(record)

        log.info("Reconciler: %d artist(s) with missing tracks", len(missing_by_artist))
        rows: list[dict] = []
        for artist_id, missing_tracks in missing_by_artist.items():
            try:
                rows.extend(self._handle_artist(artist_id, missing_tracks))
            except Exception:
                log.exception("Reconciler: failed handling artist %s", artist_id)
        return rows

    def _handle_artist(self, artist_id: int, missing_tracks: list[dict]) -> list[dict]:
        albums = self.lidarr.get_albums_for_artist(artist_id)
        owned_tracks = [t for t in self.lidarr.get_tracks(artist_id=artist_id) if t.get("hasFile")]
        albums_by_id = {a["id"]: a for a in albums if "id" in a}

        rows = []
        for missing in missing_tracks:
            row = self._handle_track(missing, owned_tracks, albums_by_id)
            if row:
                rows.append(row)
        return rows

    def _handle_track(
        self, missing: dict, owned_tracks: list[dict], albums_by_id: dict[int, dict]
    ) -> dict | None:
        key = f"track:{missing.get('id')}"
        if self.store.recently_processed("reconcile", key, self.config.reprocess_cooldown_minutes):
            return None

        title = missing.get("title")
        if not title:
            return None

        similar = find_similar_tracks(title, owned_tracks)
        if not similar:
            return None  # no lookalikes on disk - plain gap, not worth an AI call

        candidates, lookup = build_candidates(similar, albums_by_id)
        if not candidates:
            return None

        missing_album = albums_by_id.get(missing.get("albumId"), {})
        target_info = {
            "missing_track_title": title,
            "missing_album_title": missing_album.get("title"),
            "missing_album_type": missing_album.get("albumType"),
            "duration_seconds": track_duration_seconds(missing),
            "track_number": missing.get("trackNumber"),
        }

        decision = self.ai.decide(
            file_info=target_info, candidates=candidates, task_description=_TASK_DESCRIPTION
        )

        status = {"apply": "likely_duplicate", "needs_review": "uncertain", "skip": "true_gap"}[
            decision.action
        ]
        match_summary = None
        if decision.candidate_index is not None and decision.candidate_index in lookup:
            track, _release, album = lookup[decision.candidate_index]
            match_summary = f"{album.get('title')} ({album.get('albumType')}) / {track.get('title')}"

        self.store.record_decision(
            kind="reconcile",
            key=key,
            action=decision.action,
            candidate_summary=match_summary,
            confidence=decision.confidence,
            reasoning=decision.reasoning,
            applied=False,
        )
        log.info("Reconcile %s: %s - %s", title, status, decision.reasoning)

        return {
            "artist_id": missing.get("artistId"),
            "missing_track_id": missing.get("id"),
            "missing_title": title,
            "missing_album": missing_album.get("title"),
            "missing_album_type": missing_album.get("albumType"),
            "status": status,
            "matched_existing": match_summary,
            "confidence": decision.confidence,
            "reasoning": decision.reasoning,
        }
