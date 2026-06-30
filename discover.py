#!/usr/bin/env python3
"""Headless discovery: (1) concrete MDLs on the NVIDIA asset server,
(2) the real UsdPreviewSurface texture-per-input wiring of the asset(s)."""
import sys

from isaacsim import SimulationApp

app = SimulationApp({"headless": True})

import omni.client  # noqa: E402
from pxr import Usd, UsdShade  # noqa: E402
from isaacsim.storage.native import get_assets_root_path  # noqa: E402

root = get_assets_root_path()
nvidia = f"{root}/NVIDIA"
print(f"\nASSETS_ROOT = {root}")


def ls(url, filt=None):
    res, entries = omni.client.list(url)
    names = [e.relative_path for e in entries] if entries else []
    if filt:
        names = [n for n in names if filt.lower() in n.lower()]
    print(f"\n# list {url}  ({res})  [{len(names)} shown]")
    for n in sorted(names):
        print(f"   {n}")


ls(f"{nvidia}/Materials/Base/")
for cat in ("Architecture", "Masonry", "Stone", "Natural", "Ground"):
    for kw in ("concrete", "asphalt", "cement", "pavement"):
        ls(f"{nvidia}/Materials/Base/{cat}/", filt=kw)


def _find_uvtex_file(shader, depth=0):
    if shader is None or depth > 5:
        return None
    if shader.GetShaderId() == "UsdUVTexture":
        v = shader.GetInput("file").Get()
        return v.path if v else None
    for inp in shader.GetInputs():
        srcs = inp.GetConnectedSources()
        infos = srcs[0] if isinstance(srcs, tuple) else srcs
        for si in infos:
            f = _find_uvtex_file(UsdShade.Shader(si.source.GetPrim()), depth + 1)
            if f:
                return f
    return None


def texture_of(surface_shader, input_name):
    inp = surface_shader.GetInput(input_name)
    if not inp:
        return None
    srcs = inp.GetConnectedSources()
    infos = srcs[0] if isinstance(srcs, tuple) else srcs
    for si in infos:
        f = _find_uvtex_file(UsdShade.Shader(si.source.GetPrim()))
        if f:
            return f
    return None


def trace(path):
    print(f"\n##### {path}")
    stage = Usd.Stage.Open(path)
    for prim in stage.Traverse():
        if prim.GetTypeName() != "Material":
            continue
        mat = UsdShade.Material(prim)
        surf = mat.ComputeSurfaceSource()
        shader = surf[0] if isinstance(surf, tuple) else surf
        if not shader:
            print(f"  Material {prim.GetName()}: no surface shader")
            continue
        print(f"  Material {prim.GetName()}  (surface id={shader.GetShaderId()})")
        for role in ("diffuseColor", "normal", "roughness", "metallic", "opacity"):
            tex = texture_of(shader, role)
            if tex:
                print(f"      {role:12} <- {tex}")


for p in sys.argv[1:]:
    trace(p)

app.close()
