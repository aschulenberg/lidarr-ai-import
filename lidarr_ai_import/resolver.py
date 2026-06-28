from __future__ import annotations

import logging

from .ai.base import AIProvider, Decision, MatchCandidate
from .candidates import build_candidates
from .config import Config
from .lidarr_client import LidarrClient
from .matching import find_similar_tracks
from .storage import DecisionStore
from .tags import read_audio_tags

log = logging.getLogger(__name__)


class StuckImportResolver:
    """Handles files Lidarr's own importer couldn't confidently place - typically
    because the same song exists across more than one release (single/EP/album)
    for the artist and the automatic matcher scored them as a tie or a near-miss."""

    def __init__(
        self, lidarr: LidarrClient, ai: AIProvider, store: DecisionStore, config: Config
    ):
        self.lidarr = lidarr
        self.ai = ai
        self.store = store
        self.config = config

    def run_once(self) -> None:
        items: list[dict] = []
        for queue_item in self.lidarr.iter_queue():
            output_path = queue_item.get("outputPath")
            # statusMessages is how Lidarr flags "something's wrong with this
            # download" across every state name a given version might use -
            # cheaper and more robust than matching specific status enums.
            if not output_path or not queue_item.get("statusMessages"):
                continue
            try:
                items.extend(
                    self.lidarr.get_manual_import(
                        folder=output_path, download_id=queue_item.get("downloadId")
                    )
                )
            except Exception:
                log.exception("Resolver: failed scanning queue item %s", output_path)

        log.info("Resolver: %d item(s) pending manual import", len(items))
        for item in items:
            try:
                self._handle_item(item)
            except Exception:
                log.exception("Resolver: failed handling item %s", item.get("path"))

    def _handle_item(self, item: dict) -> None:
        path = item.get("path")
        if not path:
            return
        if self.store.recently_processed("resolve", path, self.config.reprocess_cooldown_minutes):
            log.debug("Resolver: skipping %s (cooldown)", path)
            return

        artist = item.get("artist")
        if not artist or not artist.get("id"):
            self._record(path, Decision.needs_review("No artist identified by Lidarr"), applied=False)
            return

        file_info = read_audio_tags(path)
        file_info["lidarr_rejections"] = [
            r.get("reason") for r in item.get("rejections", []) if r.get("reason")
        ]
        title_hint = file_info.get("title") or (item.get("tracks") or [{}])[0].get("title")
        if not title_hint:
            self._record(path, Decision.needs_review("No usable title in tags or filename"), applied=False)
            return

        candidates, lookup = self._build_candidates(artist["id"], title_hint)
        if not candidates:
            self._record(path, Decision.needs_review("No similarly-titled tracks found for this artist"), applied=False)
            return

        decision = self.ai.decide(file_info=file_info, candidates=candidates)
        self._apply(item, decision, lookup)

    def _build_candidates(
        self, artist_id: int, title_hint: str
    ) -> tuple[list[MatchCandidate], dict[int, tuple[dict, dict, dict]]]:
        albums = self.lidarr.get_albums_for_artist(artist_id)
        tracks = self.lidarr.get_tracks(artist_id=artist_id)
        similar = find_similar_tracks(title_hint, tracks)
        albums_by_id = {a["id"]: a for a in albums if "id" in a}
        return build_candidates(similar, albums_by_id)

    def _apply(
        self, item: dict, decision: Decision, lookup: dict[int, tuple[dict, dict, dict]]
    ) -> None:
        path = item.get("path")
        applied = False

        if decision.action == "apply" and decision.candidate_index is not None:
            track, release, album = lookup[decision.candidate_index]
            if track.get("hasFile"):
                decision = Decision.needs_review(
                    f"AI chose track {track['id']} but it already has a file - "
                    "won't auto-replace, needs a human look. "
                    f"(original reasoning: {decision.reasoning})"
                )
            elif decision.confidence < self.config.confidence_threshold:
                decision = Decision.needs_review(
                    f"Confidence {decision.confidence:.2f} below threshold "
                    f"{self.config.confidence_threshold:.2f}. {decision.reasoning}"
                )
            else:
                item["albumId"] = album["id"]
                item["albumReleaseId"] = release.get("id", track.get("albumReleaseId"))
                item["tracks"] = [track]
                item["trackIds"] = [track["id"]]
                if self.config.dry_run:
                    log.info(
                        "[DRY RUN] Would import %s -> %s / %s (%s)",
                        path, album.get("title"), track.get("title"), decision.reasoning,
                    )
                else:
                    self.lidarr.submit_manual_import([item])
                    log.info(
                        "Applied import: %s -> %s / %s (confidence %.2f)",
                        path, album.get("title"), track.get("title"), decision.confidence,
                    )
                applied = not self.config.dry_run

        summary = None
        if decision.candidate_index is not None and decision.candidate_index in lookup:
            track, _release, album = lookup[decision.candidate_index]
            summary = f"{album.get('title')} / {track.get('title')}"

        self._record(path, decision, applied=applied, summary=summary)

    def _record(self, path: str, decision: Decision, *, applied: bool, summary: str | None = None) -> None:
        log.info("Decision for %s: %s (confidence %.2f) - %s", path, decision.action, decision.confidence, decision.reasoning)
        self.store.record_decision(
            kind="resolve",
            key=path,
            action=decision.action,
            candidate_summary=summary,
            confidence=decision.confidence,
            reasoning=decision.reasoning,
            applied=applied,
        )
