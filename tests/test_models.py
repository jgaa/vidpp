import json

import pytest

from vidpp.errors import VidPPError
from vidpp.models import load_edit_plan


def test_rejects_overlapping_enabled_edits(tmp_path):
    path = tmp_path / "edit.json"
    path.write_text(json.dumps({"version": 1, "operations": [{"id": "a", "type": "remove", "source_start": 1, "source_end": 3}, {"id": "b", "type": "remove", "source_start": 2, "source_end": 4}]}))
    with pytest.raises(VidPPError, match="overlap"):
        load_edit_plan(path, 5)


def test_rejects_out_of_bounds_llm_edit(tmp_path):
    path = tmp_path / "edit.json"
    path.write_text(json.dumps({"version": 1, "operations": [{"id": "a", "type": "remove", "source_start": 1, "source_end": 8}]}))
    with pytest.raises(VidPPError, match="exceeds"):
        load_edit_plan(path, 5)
