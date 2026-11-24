"""Attempt a warehouse capture using OpenUSD stage loading and Kit attachment."""

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from isaacsim import SimulationApp

ASSET_ROOT = "https://omniverse-content-production.s3-us-west-2.amazonaws.com/Assets/Isaac/6.0"
STAGE_URL = ASSET_ROOT + "/Isaac/Environments/Simple_Warehouse/full_warehouse.usd"
RENDER_MODE = "RealTimePathTracing"
IMAGE_ID = "sha256:2d4ebfef053f740b634e30723e38ed736255f677553425ef35552437d74c3b21"
GPU_NAME = "NVIDIA RTX PRO 6000 Blackwell Server Edition"
ATTACH_BUDGET_S = 1200


def utc_now():
    return datetime.now(UTC).isoformat()


def resolve_render_product(stage, camera_path, reported_path):
    from pxr import UsdRender

    if reported_path:
        reported = UsdRender.Product.Get(stage, reported_path)
        if reported and camera_path in reported.GetCameraRel().GetTargets():
            return str(reported.GetPath())

    matches = []
    for prim in stage.Traverse():
        if prim.IsA(UsdRender.Product):
            product = UsdRender.Product(prim)
            if camera_path in product.GetCameraRel().GetTargets():
                matches.append(str(product.GetPath()))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one render product for {camera_path}, found {len(matches)}")
    return matches[0]


def capture(app, output):
    import carb
    import omni.replicator.core as rep
    import omni.usd
    from pxr import Gf, Usd, UsdGeom

    settings = carb.settings.get_settings()
    settings.set("/persistent/isaac/asset_root/default", ASSET_ROOT)
    stage = Usd.Stage.Open(STAGE_URL, load=Usd.Stage.LoadAll)
    if stage is None:
        raise RuntimeError("OpenUSD did not load the warehouse")
    context = omni.usd.get_context()
    # --- one-factor change: pump until exactly one RTX engine is attached (coordinator finding)
    _engine_start = time.monotonic()
    while list(context.get_attached_hydra_engine_names()) != ["rtx"]:
        app.update()
        if time.monotonic() - _engine_start > 300:
            raise TimeoutError("RTX engine did not attach within 300s")
    print(f"RTX engine present after {time.monotonic() - _engine_start:.1f}s", flush=True)
    pending = asyncio.ensure_future(context.attach_stage_async(stage))
    attach_deadline = time.monotonic() + ATTACH_BUDGET_S
    attach_updates = 0
    last_note = time.monotonic()
    while not pending.done():
        app.update()
        attach_updates += 1
        if time.monotonic() - last_note >= 30:
            last_note = time.monotonic()
            print(f"warehouse attach pending: {attach_updates} updates, "
                  f"{time.monotonic() - (attach_deadline - ATTACH_BUDGET_S):.1f}s elapsed", flush=True)
        if pending.done():
            break
        if time.monotonic() > attach_deadline:
            pending.cancel()
            raise TimeoutError(
                f"Kit did not attach the warehouse within {ATTACH_BUDGET_S}s "
                f"({attach_updates} updates)")
    print(f"warehouse attach future done after {attach_updates} updates", flush=True)
    attached, message = pending.result()
    live_stage = context.get_stage()
    meshes = sum(prim.IsA(UsdGeom.Mesh) for prim in live_stage.Traverse()) if live_stage else 0
    if not attached or not meshes:
        raise RuntimeError(f"Warehouse attachment failed ({message}, {meshes} meshes)")

    camera = UsdGeom.Camera.Define(live_stage, "/World/WarehouseBenchmarkCamera")
    camera_path = camera.GetPath()
    pose = UsdGeom.XformCommonAPI(camera)
    pose.SetTranslate(Gf.Vec3d(-8, 13, 2))
    pose.SetRotate(Gf.Vec3f(90, 0, 90), UsdGeom.XformCommonAPI.RotationOrderXYZ)
    product = rep.create.render_product(camera_path, (1280, 720), name="WarehouseBenchmark")
    for _ in range(40):
        app.update()
        if getattr(product, "path", None):
            break
    product_path = resolve_render_product(live_stage, camera_path, getattr(product, "path", None))
    writer = rep.WriterRegistry.get("BasicWriter")
    writer.initialize(output_dir=str(output), rgb=True)
    writer.attach(product)
    rep.orchestrator.set_capture_on_play(False)
    for _ in range(48):
        app.update()
    started = utc_now()
    rep.orchestrator.step(wait_for_render=True)
    rep.orchestrator.wait_until_complete()
    completed = utc_now()
    frames = list(output.glob("*.png"))
    if len(frames) != 1:
        raise RuntimeError(f"Expected one warehouse PNG, found {len(frames)}")
    frame, = frames
    frame.rename(output / "frame-720p.png")
    gpu = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], text=True
    ).strip()
    if gpu != GPU_NAME:
        raise RuntimeError("Expected exactly one visible RTX PRO 6000 Blackwell Server Edition GPU")
    receipt = {
        "image_id": os.environ["ISAAC_SIM_IMAGE_ID"],
        "sim_version": "6.0.1",
        "stage_url": STAGE_URL,
        "stage_loaded": attached,
        "warehouse_mesh_count": meshes,
        "camera_path": str(camera_path),
        "render_product": product_path,
        "render_device": gpu,
        "render_mode": settings.get("/rtx/rendermode"),
        "capture_completed": True,
        "frame_sha256": hashlib.sha256((output / "frame-720p.png").read_bytes()).hexdigest(),
        "capture_started_utc": started,
        "capture_completed_utc": completed,
    }
    (output / "capture.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    if os.environ.get("ISAAC_SIM_IMAGE_ID") != IMAGE_ID:
        raise RuntimeError("expected the pinned Isaac Sim image ID from Docker")
    output_dir = Path(sys.argv[1]).resolve()
    output_dir.mkdir()
    app = SimulationApp({
        "headless": True, "renderer": RENDER_MODE, "width": 1280, "height": 720,
        "anti_aliasing": 3, "fast_shutdown": True,
    })
    try:
        capture(app, output_dir)
    except BaseException:
        import traceback
        traceback.print_exc()
        app.close(exit_code=1)
        raise
    app.close()
