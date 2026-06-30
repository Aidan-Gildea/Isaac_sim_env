#!/usr/bin/env python3
"""Headless: dump material / shader / texture structure of USD asset(s).

    python -u inspect_asset.py <path.usdc> [<path2.usdc> ...]
"""
import sys

from isaacsim import SimulationApp

app = SimulationApp({"headless": True})

from pxr import Usd, UsdGeom, UsdShade, Sdf  # noqa: E402


def inspect(path):
    print(f"\n##### {path}")
    stage = Usd.Stage.Open(path)
    if not stage:
        print("  !! could not open")
        return
    dp = stage.GetDefaultPrim()
    print(f"  defaultPrim = {dp.GetPath() if dp else None}")
    print(f"  upAxis = {UsdGeom.GetStageUpAxis(stage)}  metersPerUnit = {UsdGeom.GetStageMetersPerUnit(stage)}")
    n_mesh = 0
    for prim in stage.Traverse():
        t = prim.GetTypeName()
        if t == "Mesh":
            n_mesh += 1
            if n_mesh <= 8:
                bound = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()[0]
                print(f"  Mesh {prim.GetPath()} -> {bound.GetPath() if bound else 'NO MATERIAL'}")
        elif t == "Shader":
            sh = UsdShade.Shader(prim)
            sid = sh.GetShaderId()
            impl = sh.GetImplementationSource()
            src = sh.GetSourceAsset() if impl == "sourceAsset" else None
            print(f"  Shader {prim.GetPath()}  id={sid!r} impl={impl} sourceAsset={src}")
            for inp in sh.GetInputs():
                if inp.GetTypeName() == Sdf.ValueTypeNames.Asset:
                    val = inp.Get()
                    rp = val.resolvedPath if val else None
                    print(f"       {inp.GetBaseName()} = {val.path if val else None}  resolved={rp!r}")
    print(f"  total meshes = {n_mesh}")


for p in sys.argv[1:]:
    inspect(p)

app.close()
