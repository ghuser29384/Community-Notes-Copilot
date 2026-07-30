#!/usr/bin/env python3
"""Run the shared server validation with the legacy API's exact millisecond timestamp format."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import server_validation as validation  # noqa: E402


def flood_payload(text: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    created_at = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    return {
        "disaster_type": "flood",
        "partnerCode": "",
        "tweetID": "",
        "sub_submission": False,
        "card_data": {"report_type": "flood", "flood_depth": 44},
        "text": text,
        "image_url": "",
        "created_at": created_at,
        "location": {"lat": -6.1754, "lng": 106.8272},
    }


validation.flood_payload = flood_payload
validation.main()
