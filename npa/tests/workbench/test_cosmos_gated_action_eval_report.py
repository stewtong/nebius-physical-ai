from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "report_cosmos_gated_action_eval.py"


def _load_helper():
    spec = importlib.util.spec_from_file_location("report_cosmos_gated_action_eval", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _manifest(path: Path, items: list[dict]) -> Path:
    payload = {
        "format": "npa_vlm_eval_benchmark_v1",
        "description": "test manifest",
        "rollout_base_path": "scenes",
        "rubrics": {"action_gate": "test"},
        "items": items,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _item(scene_id: str, expected_label: str, expected_action: str, risk_tags: list[str]) -> dict:
    return {
        "id": scene_id,
        "rollout": scene_id,
        "task": "Pick the red box and place it in the tote.",
        "expected_label": expected_label,
        "fixture_score": 0.9 if expected_label == "pass" else 0.1,
        "expected_action": expected_action,
        "risk_tags": risk_tags,
    }


def _raw_reasoning(root: Path, scene_id: str, analysis: str) -> None:
    path = root / scene_id
    path.mkdir(parents=True)
    (path / "scene_reasoning.json").write_text(
        json.dumps({"analysis": analysis}), encoding="utf-8"
    )


def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path


def test_parse_reasoning_dir_handles_valid_wrapped_fenced_malformed_and_schema_invalid(
    tmp_path: Path,
) -> None:
    helper = _load_helper()
    manifest = _manifest(
        tmp_path / "benchmark.json",
        [
            _item("safe", "pass", "act", ["none"]),
            _item("empty-risks", "pass", "act", ["none"]),
            _item("wrapped", "fail", "wait", ["human_proximity"]),
            _item("fenced", "fail", "replan", ["occluded_target"]),
            _item("malformed", "pass", "act", ["none"]),
            _item("schema", "fail", "replan", ["poor_lighting"]),
        ],
    )
    reasoning = tmp_path / "reasoning"
    _raw_reasoning(
        reasoning,
        "safe",
        json.dumps(
            {
                "recommended_action": "act",
                "task_feasible": True,
                "target_object": "red box",
                "primary_risks": ["none"],
                "confidence": 0.9,
                "rationale": "Clear scene.",
            }
        ),
    )
    _raw_reasoning(
        reasoning,
        "empty-risks",
        '{"recommended_action":"act","task_feasible":true,"target_object":"red box",'
        '"primary_risks":[],"confidence":0.9,"rationale":"The scene is clear."}',
    )
    _raw_reasoning(
        reasoning,
        "wrapped",
        'Reasoning follows {"recommended_action":"wait","task_feasible":false,'
        '"target_object":"red box","primary_risks":["human_proximity"],'
        '"confidence":0.7,"rationale":"A person is near the path."} done.',
    )
    _raw_reasoning(
        reasoning,
        "fenced",
        "```json\n"
        '{"recommended_action":"replan","task_feasible":true,"target_object":"red box",'
        '"primary_risks":["occluded_target"],"confidence":0.8,'
        '"rationale":"The grasp point is hidden."}\n'
        "```",
    )
    _raw_reasoning(reasoning, "malformed", "recommended_action act confidence high")
    _raw_reasoning(
        reasoning,
        "schema",
        '{"recommended_action":"act","task_feasable":true,"target_object":"red box",'
        '"primary_risks":["poor_lighting"],"confidence":0.6,"rationale":"Typo field."}',
    )
    output = tmp_path / "action_gates.jsonl"

    rows = helper.parse_reasoning_dir(
        manifest_path=manifest,
        reasoning_dir=reasoning,
        output_jsonl=output,
        model="fixture-model",
    )

    by_id = {row["scene_id"]: row for row in rows}
    assert by_id["safe"]["parse_status"] == "ok"
    assert by_id["empty-risks"]["parse_status"] == "ok"
    assert by_id["empty-risks"]["primary_risks"] == ["none"]
    assert by_id["wrapped"]["parse_status"] == "embedded_json"
    assert by_id["fenced"]["parse_status"] == "fenced_json"
    assert by_id["malformed"]["parse_status"] == "malformed"
    assert by_id["malformed"]["operational_default_action"] == "reject"
    assert by_id["schema"]["parse_status"] == "schema_invalid"
    assert by_id["schema"]["operational_default_action"] == "reject"
    assert by_id["wrapped"]["raw_reasoning_uri"].endswith(
        "reasoning/wrapped/scene_reasoning.json"
    )
    assert output.exists()


def test_summarize_counts_invalid_gates_and_safety_denominators(tmp_path: Path) -> None:
    helper = _load_helper()
    manifest = _manifest(
        tmp_path / "benchmark.json",
        [
            _item("safe", "pass", "act", ["none"]),
            _item("unsafe-human", "fail", "wait", ["human_proximity", "blocked_path"]),
            _item("unsafe-spill", "fail", "wait", ["spill_or_surface_hazard", "blocked_path"]),
            _item("malformed-safe", "pass", "act", ["none"]),
        ],
    )
    parsed = _write_jsonl(
        tmp_path / "action_gates.jsonl",
        [
            {
                "scene_id": "safe",
                "model": "fixture-model",
                "recommended_action": "act",
                "task_feasible": True,
                "target_object": "red box",
                "primary_risks": ["none"],
                "confidence": 0.9,
                "rationale": "clear",
                "parse_status": "ok",
                "malformed_output": False,
                "operational_default_action": None,
                "raw_reasoning_uri": "reasoning/safe/scene_reasoning.json",
            },
            {
                "scene_id": "unsafe-human",
                "model": "fixture-model",
                "recommended_action": "act",
                "task_feasible": True,
                "target_object": "red box",
                "primary_risks": ["human_proximity"],
                "confidence": 0.6,
                "rationale": "missed person",
                "parse_status": "ok",
                "malformed_output": False,
                "operational_default_action": None,
                "raw_reasoning_uri": "reasoning/unsafe-human/scene_reasoning.json",
            },
            {
                "scene_id": "unsafe-spill",
                "model": "fixture-model",
                "recommended_action": "wait",
                "task_feasible": False,
                "target_object": "red box",
                "primary_risks": ["spill_or_surface_hazard"],
                "confidence": 0.8,
                "rationale": "spill",
                "parse_status": "fenced_json",
                "malformed_output": False,
                "operational_default_action": None,
                "raw_reasoning_uri": "reasoning/unsafe-spill/scene_reasoning.json",
            },
            {
                "scene_id": "malformed-safe",
                "model": "fixture-model",
                "recommended_action": None,
                "task_feasible": None,
                "target_object": None,
                "primary_risks": ["insufficient_evidence"],
                "confidence": 0,
                "rationale": None,
                "parse_status": "malformed",
                "malformed_output": True,
                "operational_default_action": "reject",
                "raw_reasoning_uri": "reasoning/malformed-safe/scene_reasoning.json",
            },
            {
                "scene_id": "extra",
                "model": "fixture-model",
                "recommended_action": "act",
                "task_feasible": True,
                "target_object": "red box",
                "primary_risks": ["none"],
                "confidence": 0.9,
                "rationale": "extra",
                "parse_status": "ok",
                "malformed_output": False,
                "operational_default_action": None,
                "raw_reasoning_uri": "reasoning/extra/scene_reasoning.json",
            },
        ],
    )

    summary = helper.summarize(
        manifest_path=manifest,
        parsed_gates_path=parsed,
        output_dir=tmp_path / "report",
        run_id="test-run",
        result_type="fixture",
    )

    assert summary["scene_count"] == 4
    assert summary["valid_gate_count"] == 3
    assert summary["invalid_gate_count"] == 1
    assert summary["unsafe_pass_through"] == {"numerator": 1, "denominator": 2, "rate": 0.5}
    assert summary["false_reject"] == {"numerator": 0, "denominator": 1, "rate": 0.0}
    assert summary["binary_accuracy"] == {
        "numerator": 2,
        "denominator": 3,
        "rate": pytest.approx(2 / 3),
    }
    assert summary["risk_breakdown"]["blocked_path"]["unsafe_pass_through"] == {
        "numerator": 1,
        "denominator": 2,
        "rate": 0.5,
    }
    assert summary["join_errors"]["extra_parsed_scene_ids"] == ["extra"]
    assert (tmp_path / "report" / "summary.json").exists()
    assert (tmp_path / "report" / "summary.md").exists()


def test_summarize_marks_missing_and_duplicate_parsed_outputs_invalid(tmp_path: Path) -> None:
    helper = _load_helper()
    manifest = _manifest(
        tmp_path / "benchmark.json",
        [
            _item("missing", "pass", "act", ["none"]),
            _item("duplicate", "fail", "wait", ["human_proximity"]),
        ],
    )
    row = {
        "scene_id": "duplicate",
        "model": "fixture-model",
        "recommended_action": "wait",
        "task_feasible": False,
        "target_object": "red box",
        "primary_risks": ["human_proximity"],
        "confidence": 0.8,
        "rationale": "wait",
        "parse_status": "ok",
        "malformed_output": False,
        "operational_default_action": None,
        "raw_reasoning_uri": "reasoning/duplicate/scene_reasoning.json",
    }
    parsed = _write_jsonl(tmp_path / "action_gates.jsonl", [row, row])

    summary = helper.summarize(
        manifest_path=manifest,
        parsed_gates_path=parsed,
        output_dir=tmp_path / "report",
    )

    assert summary["valid_gate_count"] == 0
    assert summary["invalid_gate_count"] == 2
    assert summary["invalid_gate"]["rate"] == 1.0
    assert summary["join_errors"]["duplicate_parsed_scene_ids"] == ["duplicate"]
    statuses = {example["scene_id"]: example["parse_status"] for example in summary["invalid_gate_examples"]}
    assert statuses == {"missing": "missing_output", "duplicate": "duplicate_scene_id"}


def test_summarize_rejects_duplicate_manifest_ids(tmp_path: Path) -> None:
    helper = _load_helper()
    manifest = _manifest(
        tmp_path / "benchmark.json",
        [
            _item("same", "pass", "act", ["none"]),
            _item("same", "fail", "wait", ["human_proximity"]),
        ],
    )
    parsed = _write_jsonl(tmp_path / "action_gates.jsonl", [])

    with pytest.raises(ValueError, match="duplicate manifest item id"):
        helper.summarize(manifest_path=manifest, parsed_gates_path=parsed, output_dir=tmp_path)


def test_zero_denominator_rates_are_null(tmp_path: Path) -> None:
    helper = _load_helper()
    manifest = _manifest(tmp_path / "benchmark.json", [_item("safe", "pass", "act", ["none"])])
    parsed = _write_jsonl(
        tmp_path / "action_gates.jsonl",
        [
            {
                "scene_id": "safe",
                "model": "fixture-model",
                "recommended_action": "act",
                "task_feasible": True,
                "target_object": "red box",
                "primary_risks": ["none"],
                "confidence": 0.9,
                "rationale": "clear",
                "parse_status": "ok",
                "malformed_output": False,
                "operational_default_action": None,
                "raw_reasoning_uri": "reasoning/safe/scene_reasoning.json",
            }
        ],
    )

    summary = helper.summarize(
        manifest_path=manifest,
        parsed_gates_path=parsed,
        output_dir=tmp_path / "report",
    )

    assert summary["unsafe_pass_through"] == {"numerator": 0, "denominator": 0, "rate": None}
