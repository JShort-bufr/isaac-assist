# Modified work, 2026 — isaac-assist-frame phase 1 (Isaac Sim 6.2).
# Derived from k3street/Omniverse_Nemotron_Ext (Apache-2.0).
# Sync client for the sticky-note service API. No secrets are logged.

"""HTTP client for ``/api/v1/notes``.

``transport`` lets tests supply responses without a server. The default
transport is ``urllib`` so the Kit extension does not import aiohttp.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

Transport = Callable[[str, str, Optional[dict], Optional[dict]], dict]


def _present_flags(flags: Dict[str, Any]) -> Dict[str, Any]:
    kept = {}
    for key in ("read_only", "session_layer", "session_layer_writable"):
        if key in flags and flags[key] not in ("", False, None):
            kept[key] = flags[key]
    return kept


def _query(stage_path: str, flags: Dict[str, Any]) -> Dict[str, Any]:
    query = {"stage_path": stage_path}
    query.update(_present_flags(flags))
    return query


class NotesClientError(RuntimeError):
    def __init__(self, status: int, detail: str):
        super().__init__(f"notes http {status}")
        self.status = status
        self.detail = detail


class NotesClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8000", transport: Optional[Transport] = None):
        self.base_url = (base_url or "http://127.0.0.1:8000").rstrip("/")
        self._transport = transport

    def create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = self._request("POST", "/api/v1/notes", payload, None)
        return data.get("note", data)

    def list_notes(self, stage_path: str) -> list:
        data = self._request("GET", "/api/v1/notes", None, {"stage_path": stage_path})
        return list(data.get("notes", []))

    def delete(self, stage_path: str, note_id: str) -> Dict[str, Any]:
        return self._request(
            "DELETE",
            "/api/v1/notes",
            None,
            {"stage_path": stage_path, "id": note_id},
        )

    def send(self, stage_path: str, ids: list, **flags: Any) -> Dict[str, Any]:
        body = {"stage_path": stage_path, "ids": list(ids)}
        body.update(_present_flags(flags))
        return self._request("POST", "/api/v1/notes/send", body, None)

    def confirm(self, stage_path: str, note_id: str, **flags: Any) -> Dict[str, Any]:
        return self._request(
            "POST",
            f"/api/v1/notes/{note_id}/confirm",
            None,
            _query(stage_path, flags),
        )

    def reject(self, stage_path: str, note_id: str, **flags: Any) -> Dict[str, Any]:
        return self._request(
            "POST",
            f"/api/v1/notes/{note_id}/reject",
            None,
            _query(stage_path, flags),
        )

    def undo(self, stage_path: str, note_id: str, **flags: Any) -> Dict[str, Any]:
        return self._request(
            "POST",
            f"/api/v1/notes/{note_id}/undo",
            None,
            _query(stage_path, flags),
        )

    def review(self, stage_path: str, action: str, ids: list, **flags: Any) -> Dict[str, Any]:
        body = {"stage_path": stage_path, "action": action, "ids": list(ids)}
        body.update(_present_flags(flags))
        return self._request("POST", "/api/v1/notes/review", body, None)

    def reconcile(self, stage_path: str, prims: Dict[str, Any], **flags: Any) -> Dict[str, Any]:
        body = {"stage_path": stage_path, "prims": prims}
        body.update(_present_flags(flags))
        return self._request("POST", "/api/v1/notes/reconcile", body, None)

    def _request(
        self,
        method: str,
        path: str,
        payload: Optional[dict],
        query: Optional[dict],
    ) -> dict:
        if self._transport is not None:
            return self._transport(method, path, payload, query)
        url = self.base_url + path
        if query:
            url = url + "?" + urlencode(query)
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise NotesClientError(exc.code, raw[:300]) from exc
        except URLError as exc:
            raise NotesClientError(0, type(exc.reason).__name__ if exc.reason else "URLError") from exc
        if not raw:
            return {}
        return json.loads(raw)
