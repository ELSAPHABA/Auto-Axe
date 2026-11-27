import json
from datetime import UTC, datetime, timedelta

import pytest

from autoaxe_scraper.cnn_graphs import BLOCKS, COMPARISONS, MA


@pytest.fixture
def cnn_document():
    """Synthetic wire format, not a captured provider response."""

    def build(score=42.125, count=2):
        stamp = datetime(2026, 11, 23, 7, tzinfo=UTC)
        at = int(stamp.timestamp() * 1000)
        root = {
            "fear_and_greed": {
                "score": score,
                "rating": "fear",
                "timestamp": stamp.isoformat(),
                **dict.fromkeys(COMPARISONS, 40.5),
            },
            "unrelated": {"discard": True},
        }
        for key in BLOCKS:
            root[key] = {
                "timestamp": at,
                "data": [
                    {
                        "x": int((stamp - timedelta(days=i)).timestamp() * 1000),
                        "y": 42.125 if key == BLOCKS[0] else 123.456,
                        "rating": "fear",
                    }
                    for i in range(count)
                ],
                **({} if key in MA else {"score": score, "rating": "fear"}),
            }
        return json.dumps(root).encode()

    return build
