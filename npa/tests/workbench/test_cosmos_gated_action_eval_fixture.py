from __future__ import annotations

import json
from pathlib import Path

from PIL import Image


FIXTURE_ROOT = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "npa"
    / "workbench"
    / "vlm_eval"
    / "fixtures"
    / "cosmos_gated_action_eval"
)
ALLOWED_LABELS = {"pass", "fail"}
ALLOWED_ACTIONS = {"act", "wait", "replan", "reject"}
ALLOWED_RISKS = {
    "human_proximity",
    "occluded_target",
    "wrong_object",
    "unstable_stack",
    "spill_or_surface_hazard",
    "blocked_path",
    "poor_lighting",
    "ambiguous_target",
    "insufficient_evidence",
    "none",
}


def test_cosmos_gated_fixture_manifest_has_canonical_shape_and_assets() -> None:
    manifest = json.loads((FIXTURE_ROOT / "benchmark.json").read_text(encoding="utf-8"))
    provenance = json.loads((FIXTURE_ROOT / "provenance.json").read_text(encoding="utf-8"))

    assert manifest["format"] == "npa_vlm_eval_benchmark_v1"
    assert manifest["rollout_base_path"] == "scenes"
    assert set(manifest["rubrics"]) == {"action_gate", "strict_safety"}
    items = manifest["items"]
    assert len(items) == 8
    assert len({item["id"] for item in items}) == len(items)
    assert {item["expected_action"] for item in items} >= {"act", "wait", "replan", "reject"}

    provenance_by_scene = {item["scene_id"]: item for item in provenance["items"]}
    assert set(provenance_by_scene) == {item["id"] for item in items}

    all_risks = set()
    for item in items:
        scene_id = item["id"]
        assert item["rollout"] == scene_id
        assert item["expected_label"] in ALLOWED_LABELS
        assert item["expected_action"] in ALLOWED_ACTIONS
        assert isinstance(item["fixture_score"], float)
        assert 0.0 <= item["fixture_score"] <= 1.0
        assert item["risk_tags"]
        assert set(item["risk_tags"]) <= ALLOWED_RISKS
        all_risks.update(item["risk_tags"])

        asset_path = FIXTURE_ROOT / "scenes" / scene_id / "frame-000.jpg"
        assert asset_path.exists(), asset_path
        with Image.open(asset_path) as image:
            assert image.format == "JPEG"
            assert image.size == (1400, 900)

        provenance_item = provenance_by_scene[scene_id]
        assert provenance_item["asset_path"] == f"scenes/{scene_id}/frame-000.jpg"
        assert provenance_item["cosmos_generated"] is False
        assert "third-party image inputs" in provenance_item["license_note"]

    assert {"human_proximity", "occluded_target", "wrong_object", "unstable_stack"} <= all_risks

