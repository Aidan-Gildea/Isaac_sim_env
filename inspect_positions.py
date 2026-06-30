#!/usr/bin/env python3
"""Headless: report world-space bounding boxes (true positions) of scene prims.
    python -u inspect_positions.py out/sandbox.usd
Also reports each tree asset's intrinsic geometry offset from its local origin."""
import sys

from isaacsim import SimulationApp

app = SimulationApp({"headless": True})

from pxr import Usd, UsdGeom  # noqa: E402

stage = Usd.Stage.Open(sys.argv[1])
cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_, UsdGeom.Tokens.render])


def report(path):
    prim = stage.GetPrimAtPath(path)
    if not prim or not prim.IsValid():
        print(f"  {path}: MISSING")
        return
    rng = cache.ComputeWorldBound(prim).ComputeAlignedRange()
    mn, mx = rng.GetMin(), rng.GetMax()
    cx, cy = (mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2
    r = (cx ** 2 + cy ** 2) ** 0.5
    print(f"  {path:28} centerXY=({cx:6.2f},{cy:6.2f}) r={r:5.2f}  "
          f"x[{mn[0]:6.2f},{mx[0]:6.2f}] y[{mn[1]:6.2f},{mx[1]:6.2f}] z[{mn[2]:5.2f},{mx[2]:5.2f}]")


print("\n### scene world bounds")
for p in ("/World/Floor", "/World/Patio", "/World/Rim"):
    report(p)
for grp in ("/World/Trees", "/World/Barriers", "/World/Cones"):
    g = stage.GetPrimAtPath(grp)
    if g and g.IsValid():
        for c in g.GetChildren():
            report(c.GetPath().pathString)
report("/World/Pillar")

# intrinsic offset of each tree asset (origin vs geometry center), unscaled/untranslated
print("\n### tree asset intrinsic geometry (opened standalone)")
import os
PROJECT = os.path.dirname(os.path.abspath(__file__))
for rel in ("assets/trees/tree_small_02/tree_small_02_4k.usdc",
            "assets/trees/fir_sapling_medium/fir_sapling_medium_4k.usdc"):
    s = Usd.Stage.Open(os.path.join(PROJECT, rel))
    c2 = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_, UsdGeom.Tokens.render])
    rng = c2.ComputeWorldBound(s.GetDefaultPrim()).ComputeAlignedRange()
    mn, mx = rng.GetMin(), rng.GetMax()
    print(f"  {os.path.basename(rel):34} originOffsetXY=({(mn[0]+mx[0])/2:6.2f},{(mn[1]+mx[1])/2:6.2f}) "
          f"size=({mx[0]-mn[0]:5.2f},{mx[1]-mn[1]:5.2f},{mx[2]-mn[2]:5.2f}) z[{mn[2]:5.2f},{mx[2]:5.2f}]")

app.close()
