"""Fixed 600 s monotonic write window for benchmark_sdg.py on the full warehouse.

Vendor file is used with exactly two auditable changes, both logged to <RUN_DIR>:
 1. stage load: the vendor's `omni.usd.get_context().open_stage(env_path)` is replaced by the
    `Usd.Stage.Open(env_path, load=Usd.Stage.LoadAll)` and `attach_stage_async` sequence. The
    loaded mesh count is written to <RUN_DIR>/attach.json and must be >= 1 (observed 3,473).
 2. if the warehouse has no `/World` prim, the vendor asset-creation parent is satisfied by an
    in-memory session-layer Xform (/World). The upstream USD is never modified or saved; the
    session layer is recorded in <RUN_DIR>/session-world.json.
The vendor's benchmark phase start is used as the window origin (after build/warm-up) and the
loop is bounded by WRITE_SECONDS monotonic seconds. The vendor then drains the writer.
"""
import os
import runpy
import sys
from pathlib import Path

if "RUN_DIR" not in os.environ:
    raise RuntimeError("Set RUN_DIR to the writable results directory")
DUR = float(os.environ.get("WRITE_SECONDS", "600"))
VENDOR = "/isaac-sim/standalone_examples/benchmarks/benchmark_sdg.py"
src = Path(VENDOR).read_text()

A_OPEN = "    omni.usd.get_context().open_stage(env_path)\n"
A_START = "start_time = time.time()\nfor i in range(num_frames):"
A_STEP = "    rep.orchestrator.step(rt_subframes=rt_subframes, wait_for_render=wait_for_render)\n"
A_END = "end_time = time.time()\n"
for anchor in (A_OPEN, A_START, A_STEP, A_END):
    count = src.count(anchor)
    if count != 1:
        raise ValueError(f"Vendor anchor must appear once: {anchor!r} ({count} matches)")

LOAD = '''    # Load the full warehouse and add a session-layer /World if needed.
    import asyncio as _asyncio, json as _json, os as _os, time as _tm
    import omni.usd as _omni_usd
    from pxr import Usd as _Usd, UsdGeom as _UsdGeom, Sdf as _Sdf
    _stage = _Usd.Stage.Open(str(env_path), load=_Usd.Stage.LoadAll)
    _ctx = _omni_usd.get_context()
    _task = _asyncio.get_event_loop_policy().get_event_loop().create_task(_ctx.attach_stage_async(_stage))
    _app = omni.kit.app.get_app(); _t0 = _tm.time()
    while not _task.done():
        _app.update()
        if _tm.time() - _t0 > 300:
            raise RuntimeError("attach_stage_async timeout")
    _ok, _msg = _task.result()
    _live = _ctx.get_stage()
    _meshes = sum(1 for _p in _live.Traverse() if _p.IsA(_UsdGeom.Mesh)) if _live else 0
    _json.dump({"env_path": str(env_path), "attach_ok": bool(_ok), "attach_msg": str(_msg),
                "attach_seconds": round(_tm.time()-_t0, 2), "mesh_count": _meshes},
               open(_os.path.join(_os.environ["RUN_DIR"], "attach.json"), "w"), indent=1)
    print("Warehouse attach ok=%s meshes=%d" % (_ok, _meshes), flush=True)
    if not _ok or _meshes < 1:
        raise RuntimeError("warehouse stage not attached with meshes (ok=%s meshes=%d)" % (_ok, _meshes))
    if not _live.GetPrimAtPath("/World").IsValid():
        _sess = _live.GetSessionLayer() if hasattr(_live, "GetSessionLayer") else _live.GetRootLayer()
        if hasattr(_live, "GetEditTarget") and _live.GetSessionLayer is not None:
            _live.SetEditTarget(_Usd.EditTarget(_live.GetSessionLayer()))
        _w = _UsdGeom.Xform.Define(_live, "/World")
        _json.dump({"created": "/World", "layer": str(_sess.identifier) if _sess else "unknown",
                    "upstream_modified": False}, open(_os.path.join(_os.environ["RUN_DIR"], "session-world.json"), "w"), indent=1)
        print("Created session-layer /World in memory", flush=True)
    else:
        _json.dump({"created": None, "reason": "/World already present", "upstream_modified": False},
                   open(_os.path.join(_os.environ["RUN_DIR"], "session-world.json"), "w"), indent=1)
    # restore the default edit target for the vendor's own asset creation
    try:
        _live.SetEditTarget(_Usd.EditTarget(_live.GetRootLayer()))
    except Exception:
        pass
'''

START = ("start_time = time.time()\n"
         "import json as _json, os as _os, time as _tm\n"
         "_win_t0 = _tm.monotonic(); _frames = 0\n"
         "for i in range(num_frames):\n"
         f"    if _tm.monotonic() - _win_t0 >= {DUR!r}:\n"
         "        break\n")
src = src.replace(A_OPEN, LOAD, 1)
src = src.replace(A_START, START, 1)
src = src.replace(A_STEP, A_STEP + "    _frames += 1\n", 1)
END = ("end_time = time.time()\n"
       f"_json.dump({{'requested_window_s': {DUR!r}, 'monotonic_elapsed_s': _tm.monotonic()-_win_t0,\n"
       "            'frames_in_window': _frames},\n"
       "           open(_os.path.join(_os.environ['RUN_DIR'], 'window.json'), 'w'), indent=1)\n")
src = src.replace(A_END, END, 1)
tmp = Path(f"/tmp/benchmark_sdg_timed_{os.getpid()}.py")
with tmp.open("x") as staged:
    staged.write(src)
sys.argv[0] = str(tmp)
runpy.run_path(str(tmp), run_name="__main__")
