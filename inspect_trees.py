#!/usr/bin/env python3
"""Headless: report native units + bbox size/z-range of each Isaac vegetation tree."""
from isaacsim import SimulationApp

app = SimulationApp({"headless": True})

from pxr import Usd, UsdGeom  # noqa: E402

try:
    from isaacsim.storage.native import get_assets_root_path
except Exception:
    from isaacsim.core.utils.nucleus import get_assets_root_path

ROOT = get_assets_root_path()
TREES = ["Douglas_Fir", "White_Pine", "Yellow_Pine", "Red_Maple", "Sugar_Maple",
         "Japanese_Maple", "Red_Oak", "Scarlet_Oak", "Gray_Birch", "Black_Oak",
         "Orange_Tree", "Shumard_Oak", "Elm_Sapling"]

for name in TREES:
    url = f"{ROOT}/NVIDIA/Assets/Vegetation/Trees/{name}.usd"
    try:
        s = Usd.Stage.Open(url)
        mpu = UsdGeom.GetStageMetersPerUnit(s)
        up = UsdGeom.GetStageUpAxis(s)
        c = UsdGeom.BBoxCache(Usd.TimeCode.Default(),
                              [UsdGeom.Tokens.default_, UsdGeom.Tokens.render])
        rng = c.ComputeWorldBound(s.GetDefaultPrim()).ComputeAlignedRange()
        mn, mx = rng.GetMin(), rng.GetMax()
        sz = (mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2])
        print(f"{name:16} mpu={mpu:<6} up={up} size=({sz[0]:7.2f},{sz[1]:7.2f},{sz[2]:7.2f}) "
              f"z[{mn[2]:8.2f},{mx[2]:8.2f}]  height_m={sz[2]*mpu:6.2f}", flush=True)
    except Exception as e:
        print(f"{name:16} ERROR {e}", flush=True)

app.close()
