from __future__ import annotations

import logging
from typing import Any

import requests

log = logging.getLogger(__name__)


class LidarrError(RuntimeError):
    pass


class LidarrClient:
    """Thin wrapper around the Lidarr v1 REST API.

    Deliberately returns raw dicts/lists from the API instead of our own models.
    Manual-import payloads in particular get round-tripped: we fetch Lidarr's own
    candidate object, mutate only the fields the AI decided on, and POST that same
    object back. That way we never have to hardcode the exact field set for a given
    Lidarr version - whatever shape Lidarr handed us is the shape it gets back.
    """

    def __init__(self, base_url: str, api_key: str, timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"X-Api-Key": api_key, "Accept": "application/json"})

    def _url(self, path: str) -> str:
        return f"{self.base_url}/api/v1/{path.lstrip('/')}"

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = self._url(path)
        try:
            resp = self.session.request(method, url, timeout=self.timeout, **kwargs)
        except requests.RequestException as exc:
            raise LidarrError(f"{method} {url} failed: {exc}") from exc
        if not resp.ok:
            raise LidarrError(f"{method} {url} -> {resp.status_code}: {resp.text[:500]}")
        if not resp.content:
            return None
        return resp.json()

    def test_connection(self) -> dict:
        return self._request("GET", "system/status")

    # ---- artists / albums / tracks -------------------------------------------------

    def get_all_artists(self) -> list[dict]:
        return self._request("GET", "artist") or []

    def get_artist(self, artist_id: int) -> dict:
        return self._request("GET", f"artist/{artist_id}")

    def get_albums_for_artist(self, artist_id: int) -> list[dict]:
        return self._request("GET", "album", params={"artistId": artist_id}) or []

    def get_album(self, album_id: int) -> dict:
        """Includes releases (and each release's tracks aren't inlined - use get_tracks)."""
        return self._request("GET", f"album/{album_id}")

    def get_tracks(self, artist_id: int | None = None, album_id: int | None = None) -> list[dict]:
        params: dict[str, Any] = {}
        if artist_id is not None:
            params["artistId"] = artist_id
        if album_id is not None:
            params["albumId"] = album_id
        return self._request("GET", "track", params=params) or []

    # ---- wanted / missing -----------------------------------------------------------

    def iter_wanted_missing(self, page_size: int = 100):
        page = 1
        while True:
            data = self._request(
                "GET",
                "wanted/missing",
                params={"page": page, "pageSize": page_size, "includeArtist": True},
            )
            records = (data or {}).get("records", [])
            if not records:
                return
            yield from records
            total_records = (data or {}).get("totalRecords", 0)
            if page * page_size >= total_records:
                return
            page += 1

    # ---- queue ------------------------------------------------------------------------

    def iter_queue(self, page_size: int = 100):
        page = 1
        while True:
            data = self._request(
                "GET", "queue", params={"page": page, "pageSize": page_size}
            )
            records = (data or {}).get("records", [])
            if not records:
                return
            yield from records
            total_records = (data or {}).get("totalRecords", 0)
            if page * page_size >= total_records:
                return
            page += 1

    # ---- manual import ---------------------------------------------------------------

    def get_manual_import(self, folder: str, download_id: str | None = None) -> list[dict]:
        """`folder` is required - Lidarr's endpoint throws a 500 ("path" can't be
        empty) if it's omitted, it does NOT default to scanning everything.

        Scope this to one queue item's outputPath at a time (see iter_queue),
        not a whole root/library folder - scanning an entire library on every
        poll is expensive enough on slower (e.g. NAS/array) storage to time out.
        """
        params: dict[str, Any] = {"folder": folder}
        if download_id:
            params["downloadId"] = download_id
        return self._request("GET", "manualimport", params=params) or []

    def submit_manual_import(self, items: list[dict], import_mode: str = "auto") -> dict:
        body = {"name": "ManualImport", "files": items, "importMode": import_mode}
        return self._request("POST", "command", json=body)

    def get_command(self, command_id: int) -> dict:
        return self._request("GET", f"command/{command_id}")
