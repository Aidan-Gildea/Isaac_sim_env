#!/usr/bin/env python3
"""Headless: inspect placed tree prims for payloads / LOD variant sets / visibility / purpose
that could explain why only the nearest tree renders foliage."""
import sys
from isaacsim import SimulationApp
app = SimulationApp({"headless": True})
from pxr import Usd, UsdGeom  # noqa: E402

stage = Usd.Stage.Open(sys.argv[1])
trees = stage.GetPrimAtPath("/World/Trees")
for t in trees.GetChildren():
    name = t.GetName()
    vsets = t.GetVariantSets().GetNames()
    sel = {v: t.GetVariantSets().GetVariantSelection(v) for v in vsets}
    has_payload = t.HasAuthoredPayloads()
    # count imageable mesh prims + purposes under this tree
    nmesh = nimg = 0
    purposes = set()
    vis_invisible = 0
    for p in Usd.PrimRange(t):
        if p.IsA(UsdGeom.Mesh):
            nmesh += 1
        img = UsdGeom.Imageable(p)
        if img:
            nimg += 1
            pur = img.GetPurposeAttr().Get()
            if pur:
                purposes.add(str(pur))
            vis = img.GetVisibilityAttr().Get()
            if vis == UsdGeom.Tokens.invisible:
                vis_invisible += 1
    print(f"{name:9} payload={has_payload} vsets={vsets} sel={sel} "
          f"meshes={nmesh} invisible={vis_invisible} purposes={purposes}", flush=True)
app.close()
