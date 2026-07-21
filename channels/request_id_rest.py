import re
from typing import Any, Dict, Optional, Text

from rasa.core.channels.rest import RestInput
from sanic.request import Request


class RequestIdRest(RestInput):
    """Rasa 3.0 REST channel that preserves the frontend request_id."""

    def get_metadata(self, request: Request) -> Optional[Dict[Text, Any]]:
        body = request.json if isinstance(request.json, dict) else {}
        supplied = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
        candidate = request.headers.get("x-request-id") or supplied.get("request_id")
        metadata = dict(supplied)
        if isinstance(candidate, str) and re.fullmatch(r"[A-Za-z0-9_-]{8,64}", candidate):
            metadata["request_id"] = candidate
        else:
            metadata.pop("request_id", None)
        return metadata
