"""Patch only the stage-loading statement in the installed camera benchmark."""
import argparse
import hashlib
import json
from pathlib import Path

VENDOR_SHA256 = "8193fed9a96a9b5644387cf6dac5ef342d9497f4f95989db1348c7a5a0a454f0"
TARGET = b"benchmark.fully_load_stage(benchmark.assets_root_path + scene_path)"
REPLACEMENT = b'''def _open_and_attach_warehouse(path):
    import asyncio
    import json
    import time
    import omni.kit.app
    import omni.usd
    from pxr import Usd, UsdGeom

    stage = Usd.Stage.Open(str(path), load=Usd.Stage.LoadAll)
    if stage is None:
        raise RuntimeError("OpenUSD did not load the warehouse")
    context = omni.usd.get_context()
    attachment = asyncio.ensure_future(context.attach_stage_async(stage))
    app = omni.kit.app.get_app()
    deadline = time.monotonic() + 300
    while not attachment.done():
        app.update()
        if time.monotonic() > deadline:
            raise TimeoutError("Kit did not attach the warehouse")
    attached, message = attachment.result()
    live_stage = context.get_stage()
    meshes = sum(prim.IsA(UsdGeom.Mesh) for prim in live_stage.Traverse()) if live_stage else 0
    if not attached or not meshes:
        raise RuntimeError(f"Warehouse attachment failed ({message}, {meshes} meshes)")
    print(json.dumps({"warehouse_mesh_count": meshes, "stage_loaded": True, "stage": str(path)}), flush=True)

_open_and_attach_warehouse(benchmark.assets_root_path + scene_path)'''


def stage(source, destination):
    original = source.read_bytes()
    vendor_digest = hashlib.sha256(original).hexdigest()
    if vendor_digest != VENDOR_SHA256:
        raise ValueError(f"expected vendor SHA-256 {VENDOR_SHA256}, got {vendor_digest}")
    if original.count(TARGET) != 1:
        raise ValueError("expected exactly one matching vendor stage-load statement")
    line_start = original.rfind(b"\n", 0, original.index(TARGET)) + 1
    indent = original[line_start:original.index(TARGET)]
    if indent.strip():
        raise ValueError("stage-load target must begin a statement")
    patched = original.replace(TARGET, REPLACEMENT.replace(b"\n", b"\n" + indent), 1)
    compile(patched, str(destination), "exec")
    with destination.open("xb") as handle:
        handle.write(patched)
    return {"vendor_sha256": vendor_digest,
            "staged_sha256": hashlib.sha256(patched).hexdigest(), "statements_replaced": 1}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(json.dumps(stage(args.source, args.destination)))
