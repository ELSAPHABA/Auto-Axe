import pytest

from autoaxe.application.cnn_graphs import BLOCKS, COMPARISONS, MA


@pytest.fixture
def cnn_details():
    def build(stamp):
        return {
            "comparisons": dict.fromkeys(COMPARISONS, "40.5"),
            "blocks": {
                key: {
                    "timestamp": stamp,
                    "score": None if key in MA else "65",
                    "rating": None if key in MA else "Greed",
                    "data": [[stamp, "65" if key == BLOCKS[0] else "123.456", "Greed"]],
                }
                for key in BLOCKS
            },
        }

    return build
