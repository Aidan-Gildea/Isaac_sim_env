#!/usr/bin/env python3
"""Headless: (1) report tree base-z (find floaters) in a usd; (2) list dirt/ground MDLs."""
import sys
from isaacsim import SimulationApp
app = SimulationApp({"headless": True})
import omni.client  # noqa
from pxr import Usd, UsdGeom  # noqa
try:
    from isaacsim.storage.native import get_assets_root_path
except Exception:
    from isaacsim.core.utils.nucleus import get_assets_root_path
ROOT = get_assets_root_path()

# (1) tree base z
usd = sys.argv[1] if len(sys.argv) > 1 else "out/iter_018.usd"
stage = Usd.Stage.Open(usd)
cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_, UsdGeom.Tokens.render])
print(f"\n### tree base-z in {usd} (floor top = z 0; base should be ~0)")
trees = stage.GetPrimAtPath("/World/Trees")
if trees:
    for t in trees.GetChildren():
        rng = cache.ComputeWorldBound(t).ComputeAlignedRange()
        mn, mx = rng.GetMin(), rng.GetMax()
        flag = "  <-- FLOATING" if mn[2] > 0.15 else ("  <-- SUNK" if mn[2] < -0.15 else "")
        print(f"  {t.GetName():9} base_z={mn[2]:6.2f} top_z={mx[2]:6.2f} h={mx[2]-mn[2]:5.2f}{flag}")

# (2) dirt/ground MDLs
print("\n### dirt/ground/soil MDLs under NVIDIA/Materials/Base")
for cat in ("Natural", "Ground", "Stone", "Masonry"):
    url = f"{ROOT}/NVIDIA/Materials/Base/{cat}"
    res, entries = omni.client.list(url)
    if res != omni.client.Result.OK:
        continue
    for e in entries:
        n = e.relative_path
        if n.lower().endswith(".mdl") and any(k in n.lower() for k in
                                              ("dirt", "ground", "soil", "gravel", "mud", "sand", "earth", "grass")):
            print(f"  {cat}/{n}")
app.close()
