#!/usr/bin/env python3
"""SceneBuilder: authors the inspection-plaza scene onto a USD stage from a SceneConfig.

Import this ONLY after a SimulationApp has been created (it pulls in isaacsim/pxr modules).
Both launch_scene.py (interactive GUI) and render_scene.py (headless capture) use this so the
scene definition lives in exactly one place.
"""
import glob
import math
import os

import numpy as np
from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdPhysics, UsdShade
from isaacsim.core.utils.stage import add_reference_to_stage

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

# --- fixed asset locations (not per-config) ---
BARRIER_USD = os.path.join(PROJECT_DIR, "assets/barriers/concrete_road_barrier/concrete_road_barrier_4k.usdc")
TREE_USDS = [
    os.path.join(PROJECT_DIR, "assets/trees/tree_small_02/tree_small_02_4k.usdc"),
    os.path.join(PROJECT_DIR, "assets/trees/fir_sapling_medium/fir_sapling_medium_4k.usdc"),
]
CONE_REL = "/Isaac/Environments/Simple_Warehouse/Props/S_TrafficCone.usd"
VEG_TREE_REL = "/NVIDIA/Assets/Vegetation/Trees/{}.usd"
RIM_MDL = ("Masonry", "Concrete_Rough")
PILLAR_MDL = ("Masonry", "Concrete_Formed")
_BTEX = os.path.join(PROJECT_DIR, "assets/barriers/concrete_road_barrier/textures")
CONCRETE_NOR = os.path.join(_BTEX, "concrete_road_barrier_nor_gl_4k.exr")
CONCRETE_ROUGH = os.path.join(_BTEX, "concrete_road_barrier_rough_4k.exr")
GRAVEL_NOR = os.path.join(PROJECT_DIR, "assets/textures/gravel_nrm.png")
GRAVEL_ROUGH = os.path.join(PROJECT_DIR, "assets/textures/gravel_rough.png")
PATIO_NOR = os.path.join(PROJECT_DIR, "assets/textures/patio_nrm.png")  # gravel + horizontal grooves
PATIO_NOISE = os.path.join(PROJECT_DIR, "assets/textures/patio_noise.png")  # albedo mottle (mean 0.90)
CONCRETE_NOISE = os.path.join(PROJECT_DIR, "assets/textures/concrete_noise.png")  # imperfection blotches
NOISE_MEAN = 0.90
DIRT_MDL = ("Natural", "Dirt")
SPALLS_DIR = os.path.join(PROJECT_DIR, "Spalls")
CRACKS_DIR = os.path.join(PROJECT_DIR, "cracks")
CRACK_DIFF = os.path.join(PROJECT_DIR, "assets/textures/crack_diff.png")     # crack colour
CRACK_OPAC = os.path.join(PROJECT_DIR, "assets/textures/crack_opacity.png")  # crack mask (white=crack)
SPOT_DIFF = os.path.join(PROJECT_DIR, "assets/textures/spot_diff.png")       # stain colour
SPOT_OPAC = os.path.join(PROJECT_DIR, "assets/textures/spot_opacity.png")    # stain mask


def get_asset_root():
    try:
        from isaacsim.storage.native import get_assets_root_path
    except Exception:  # pragma: no cover
        from isaacsim.core.utils.nucleus import get_assets_root_path
    try:
        return get_assets_root_path()
    except Exception as exc:  # pragma: no cover
        print(f"[warn] asset root unavailable: {exc}")
        return None


class SceneBuilder:
    def __init__(self, stage, cfg, asset_root=None):
        self.stage = stage
        self.cfg = cfg
        self.asset_root = asset_root if asset_root is not None else get_asset_root()
        self.rng = np.random.default_rng(cfg.seed)
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
        UsdGeom.SetStageMetersPerUnit(stage, 1.0)
        UsdGeom.Xform.Define(stage, "/World")
        stage.SetDefaultPrim(stage.GetPrimAtPath("/World"))

    # ------------------------------------------------------------------ helpers
    def set_transform(self, prim_path, translate=(0.0, 0.0, 0.0), rotate_z=0.0, scale=None):
        xf = UsdGeom.Xformable(self.stage.GetPrimAtPath(prim_path))
        xf.ClearXformOpOrder()
        xf.AddTranslateOp().Set(Gf.Vec3d(*translate))
        if rotate_z:
            xf.AddRotateZOp().Set(float(rotate_z))
        if scale is not None:
            xf.AddScaleOp().Set(Gf.Vec3f(*scale))

    def _shader_of(self, mat_path):
        for child in self.stage.GetPrimAtPath(mat_path).GetChildren():
            if child.GetTypeName() == "Shader":
                return UsdShade.Shader(child)
        return None

    def bind_material(self, prim, mat_path):
        mat = UsdShade.Material(self.stage.GetPrimAtPath(mat_path))
        UsdShade.MaterialBindingAPI.Apply(prim)
        UsdShade.MaterialBindingAPI(prim).Bind(mat)

    def bind_material_all(self, root_prim, mat_path):
        """Bind one material to every mesh + geom-subset under a referenced asset (overrides the
        asset's own per-mesh bindings)."""
        n = 0
        for p in Usd.PrimRange(root_prim):
            if p.GetTypeName() in ("Mesh", "GeomSubset"):
                self.bind_material(p, mat_path)
                n += 1
        return n

    def make_omnipbr(self, mat_path, name, color=None):
        from isaacsim.core.api.materials import OmniPBR
        OmniPBR(prim_path=mat_path, name=name,
                **({"color": np.array(color, dtype=float)} if color else {}))
        return mat_path

    def make_emissive(self, mat_path, name, color):
        from isaacsim.core.api.materials import OmniPBR
        OmniPBR(prim_path=mat_path, name=name, color=np.array(color, dtype=float))
        sh = self._shader_of(mat_path)
        if sh is not None:
            sh.CreateInput("enable_emission", Sdf.ValueTypeNames.Bool).Set(True)
            sh.CreateInput("emissive_color", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
            sh.CreateInput("emissive_intensity", Sdf.ValueTypeNames.Float).Set(900.0)
            sh.CreateInput("reflection_roughness_constant", Sdf.ValueTypeNames.Float).Set(0.6)
        return mat_path

    def make_concrete_grey(self, mat_path, name, grey, tile, roughness,
                           normal_tex=CONCRETE_NOR, rough_tex=CONCRETE_ROUGH, albedo_noise_tex=None):
        """Grey surface with rough-surface relief from a normal/roughness map, triplanar-projected.
        Colour = `grey` is kept (the mean), but the *texture* can change via normal_tex (e.g. gravelly
        asphalt). If albedo_noise_tex is given, it mottles the albedo (mean 0.90, compensated by tint)
        so the mean colour is preserved while adding visible grain."""
        from isaacsim.core.api.materials import OmniPBR
        sh = None
        if albedo_noise_tex and os.path.isfile(albedo_noise_tex):
            OmniPBR(prim_path=mat_path, name=name, texture_path=albedo_noise_tex)
            sh = self._shader_of(mat_path)
            if sh is not None:
                t = grey / NOISE_MEAN  # tint compensates the noise mean -> rendered mean ~= grey
                sh.CreateInput("diffuse_tint", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(t, t, t))
        else:
            OmniPBR(prim_path=mat_path, name=name)
            sh = self._shader_of(mat_path)
            if sh is not None:
                sh.CreateInput("diffuse_color_constant", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(grey, grey, grey))
        if sh is None:
            return mat_path
        sh.CreateInput("project_uvw", Sdf.ValueTypeNames.Bool).Set(True)
        sh.CreateInput("texture_scale", Sdf.ValueTypeNames.Float2).Set(Gf.Vec2f(tile, tile))
        if normal_tex and os.path.isfile(normal_tex):
            sh.CreateInput("normalmap_texture", Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath(normal_tex))
        if rough_tex and os.path.isfile(rough_tex):
            sh.CreateInput("reflectionroughness_texture", Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath(rough_tex))
            sh.CreateInput("reflection_roughness_texture_influence", Sdf.ValueTypeNames.Float).Set(1.0)
        sh.CreateInput("reflection_roughness_constant", Sdf.ValueTypeNames.Float).Set(roughness)
        return mat_path

    def make_decal(self, mat_path, name, diffuse_png, opacity_png, obj_w, obj_h, threshold=0.25, tint=None):
        """Decal material (iter_037 baseline). OBJECT-space triplanar with texture_scale=1/(quad size)
        so one tile maps onto the quad. OmniPBR's opacity_texture reads a MONO value, so opacity_png
        must be a GRAYSCALE mask (shape white on black)."""
        from isaacsim.core.api.materials import OmniPBR
        OmniPBR(prim_path=mat_path, name=name, texture_path=diffuse_png)
        sh = self._shader_of(mat_path)
        if sh is not None:
            sh.CreateInput("project_uvw", Sdf.ValueTypeNames.Bool).Set(True)
            sh.CreateInput("world_or_object", Sdf.ValueTypeNames.Bool).Set(False)
            sh.CreateInput("texture_scale", Sdf.ValueTypeNames.Float2).Set(Gf.Vec2f(1.0 / obj_w, 1.0 / obj_h))
            sh.CreateInput("texture_translate", Sdf.ValueTypeNames.Float2).Set(Gf.Vec2f(0.5, 0.5))
            sh.CreateInput("enable_opacity", Sdf.ValueTypeNames.Bool).Set(True)
            sh.CreateInput("enable_opacity_texture", Sdf.ValueTypeNames.Bool).Set(True)
            sh.CreateInput("opacity_texture", Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath(opacity_png))
            sh.CreateInput("opacity_threshold", Sdf.ValueTypeNames.Float).Set(threshold)
            sh.CreateInput("reflection_roughness_constant", Sdf.ValueTypeNames.Float).Set(0.85)
            if tint is not None:
                sh.CreateInput("diffuse_tint", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(tint, tint, tint))
        return mat_path

    def make_mdl_material(self, mat_path, mdl, project=True, scale=2.0, fallback_color=(0.5, 0.5, 0.5)):
        if self.asset_root is None:
            return self.make_omnipbr(mat_path, os.path.basename(mat_path), color=fallback_color)
        category, mtl_name = mdl
        url = f"{self.asset_root}/NVIDIA/Materials/Base/{category}/{mtl_name}.mdl"
        try:
            mat = UsdShade.Material.Define(self.stage, mat_path)
            shader = UsdShade.Shader.Define(self.stage, mat_path + "/Shader")
            shader.SetSourceAsset(Sdf.AssetPath(url), "mdl")
            shader.SetSourceAssetSubIdentifier(mtl_name, "mdl")
            shader.GetImplementationSourceAttr().Set(UsdShade.Tokens.sourceAsset)
            mat.CreateSurfaceOutput("mdl").ConnectToSource(shader.ConnectableAPI(), "out")
            if project:
                shader.CreateInput("project_uvw", Sdf.ValueTypeNames.Bool).Set(True)
                shader.CreateInput("texture_scale", Sdf.ValueTypeNames.Float2).Set(Gf.Vec2f(scale, scale))
            return mat_path
        except Exception as exc:  # pragma: no cover
            print(f"[warn] MDL material {mtl_name} failed ({exc}); using grey OmniPBR")
            return self.make_omnipbr(mat_path, mtl_name, color=fallback_color)

    def add_quad(self, path, half):
        # Use Omni's Plane primitive: a unit (1x1, half=0.5) +Z quad whose `st` UVs are authored the
        # way RTX recognizes (a hand-built mesh's UVs were sampled as a single texel -> decals invisible).
        import omni.kit.commands
        omni.kit.commands.execute("CreateMeshPrimWithDefaultXform", prim_type="Plane",
                                  prim_path=path, select_new_prim=False)
        prim = self.stage.GetPrimAtPath(path)
        mesh = UsdGeom.Mesh(prim)
        mesh.CreateDoubleSidedAttr(True)
        # strip the command's default (double-precision) xform ops so our float ops don't clash
        UsdGeom.Xformable(prim).ClearXformOpOrder()
        for a in list(prim.GetAttributes()):
            if a.GetName().startswith("xformOp:"):
                prim.RemoveProperty(a.GetName())
        return mesh

    def add_collider(self, prim, dynamic=False, approximation="convexHull"):
        try:
            UsdPhysics.CollisionAPI.Apply(prim)
            for child in Usd.PrimRange(prim):
                if child.IsA(UsdGeom.Mesh):
                    UsdPhysics.CollisionAPI.Apply(child)
                    UsdPhysics.MeshCollisionAPI.Apply(child).CreateApproximationAttr().Set(approximation)
            if dynamic:
                UsdPhysics.RigidBodyAPI.Apply(prim)
                UsdPhysics.MassAPI.Apply(prim)
        except Exception as exc:  # pragma: no cover
            print(f"[warn] collider setup failed for {prim.GetPath()}: {exc}")

    # --- UsdPreviewSurface -> OmniPBR conversion (Blender assets render red in RTX) ---
    def _find_uvtex_file(self, shader, depth=0):
        if shader is None or depth > 5:
            return None
        if shader.GetShaderId() == "UsdUVTexture":
            v = shader.GetInput("file").Get()
            return v.path if v else None
        for inp in shader.GetInputs():
            srcs = inp.GetConnectedSources()
            infos = srcs[0] if isinstance(srcs, tuple) else srcs
            for si in infos:
                f = self._find_uvtex_file(UsdShade.Shader(si.source.GetPrim()), depth + 1)
                if f:
                    return f
        return None

    def _texture_of(self, surface_shader, input_name):
        inp = surface_shader.GetInput(input_name)
        if not inp:
            return None
        srcs = inp.GetConnectedSources()
        infos = srcs[0] if isinstance(srcs, tuple) else srcs
        for si in infos:
            f = self._find_uvtex_file(UsdShade.Shader(si.source.GetPrim()))
            if f:
                return f
        return None

    def convert_to_omnipbr(self, root_prim, mat_scope, asset_dir):
        from isaacsim.core.api.materials import OmniPBR

        def abspath(rel):
            if not rel:
                return None
            rel = rel.replace("\\", "/")
            return rel if os.path.isabs(rel) else os.path.normpath(os.path.join(asset_dir, rel.lstrip("./")))

        def alpha_8bit(p):
            cand = (p[:-4] + "_8b.png") if p else None
            return cand if (cand and os.path.isfile(cand)) else p

        mesh_bindings, mat_inputs = [], {}
        for prim in Usd.PrimRange(root_prim):
            tn = prim.GetTypeName()
            if tn in ("Mesh", "GeomSubset"):
                bm, _ = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
                if bm and bm.GetPrim().IsValid():
                    mesh_bindings.append((prim, bm.GetPrim().GetPath().pathString))
            elif tn == "Material":
                surf = UsdShade.Material(prim).ComputeSurfaceSource()
                shader = surf[0] if isinstance(surf, tuple) else surf
                if not shader:
                    continue
                roles = {}
                for usd_in, role in (("diffuseColor", "diffuse"), ("normal", "normal"),
                                     ("roughness", "rough"), ("opacity", "opacity")):
                    t = self._texture_of(shader, usd_in)
                    if t:
                        roles[role] = abspath(t)
                mat_inputs[prim.GetPath().pathString] = roles

        UsdGeom.Scope.Define(self.stage, mat_scope)
        new_mats = {}
        for i, (mpath, tex) in enumerate(mat_inputs.items()):
            npath = f"{mat_scope}/Mat_{i}"
            OmniPBR(prim_path=npath, name=f"omnipbr_{i}",
                    **({"texture_path": tex["diffuse"]} if tex.get("diffuse") else {}))
            sh = self._shader_of(npath)
            if sh is not None:
                def set_asset(n, v):
                    if v:
                        sh.CreateInput(n, Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath(v))
                set_asset("normalmap_texture", tex.get("normal"))
                set_asset("reflectionroughness_texture", tex.get("rough"))
                if tex.get("rough"):
                    sh.CreateInput("reflection_roughness_texture_influence", Sdf.ValueTypeNames.Float).Set(1.0)
                if tex.get("opacity"):
                    sh.CreateInput("enable_opacity", Sdf.ValueTypeNames.Bool).Set(True)
                    sh.CreateInput("enable_opacity_texture", Sdf.ValueTypeNames.Bool).Set(True)
                    set_asset("opacity_texture", alpha_8bit(tex.get("opacity")))
                    sh.CreateInput("opacity_threshold", Sdf.ValueTypeNames.Float).Set(0.5)
            new_mats[mpath] = npath

        rebound = 0
        for prim, mpath in mesh_bindings:
            if mpath in new_mats:
                self.bind_material(prim, new_mats[mpath])
                rebound += 1
        return len(new_mats)

    # ------------------------------------------------------------------ scene parts
    def build_physics(self):
        scene = UsdPhysics.Scene.Define(self.stage, "/World/PhysicsScene")
        scene.CreateGravityDirectionAttr(Gf.Vec3f(0.0, 0.0, -1.0))
        scene.CreateGravityMagnitudeAttr(9.81)

    def build_ground(self):
        c = self.cfg
        floor = UsdGeom.Cube.Define(self.stage, "/World/Floor")
        self.set_transform("/World/Floor", translate=(0.0, 0.0, -0.2),
                           scale=(c.floor_half, c.floor_half, 0.2))
        if c.floor_dirt:  # dirt ground around the plaza (real Omniverse Dirt material)
            floor_mat = self.make_mdl_material("/World/Looks/FloorDirt", DIRT_MDL, scale=c.floor_tile,
                                               fallback_color=(0.30, 0.22, 0.15))
        else:
            floor_mat = self.make_concrete_grey("/World/Looks/FloorConcrete", "floor_concrete",
                                                c.floor_grey, c.floor_tile, c.floor_rough)
        self.bind_material(floor.GetPrim(), floor_mat)
        self.add_collider(floor.GetPrim(), dynamic=False)

        patio = UsdGeom.Cube.Define(self.stage, "/World/Patio")
        self.set_transform("/World/Patio", translate=(0.0, 0.0, c.patio_top / 2.0),
                           scale=(c.patio_half, c.patio_half, c.patio_top / 2.0))
        # patio: gravelly asphalt relief (no lines), SAME colour (patio_grey)
        p_nor = GRAVEL_NOR if c.patio_gravel else CONCRETE_NOR
        p_rgh = GRAVEL_ROUGH if c.patio_gravel else CONCRETE_ROUGH
        p_noise = PATIO_NOISE if c.patio_gravel else None
        self.bind_material(patio.GetPrim(),
                           self.make_concrete_grey("/World/Looks/PatioConcrete", "patio_concrete",
                                                   c.patio_grey, c.patio_tile, c.patio_rough,
                                                   normal_tex=p_nor, rough_tex=p_rgh,
                                                   albedo_noise_tex=p_noise))
        self.add_collider(patio.GetPrim(), dynamic=False)

        if c.rim_grey > 0:
            rim_mat = self.make_concrete_grey("/World/Looks/RimConcrete", "rim_concrete",
                                              c.rim_grey, tile=6.0, roughness=0.9)
        else:
            rim_mat = self.make_mdl_material("/World/Looks/RimConcrete", RIM_MDL, scale=2.0,
                                             fallback_color=(0.4, 0.4, 0.42))
        outer = c.patio_half + c.rim_bar
        bars = {
            "N": ((0.0, outer, c.rim_top / 2.0), (c.patio_half + 2 * c.rim_bar, c.rim_bar, c.rim_top / 2.0)),
            "S": ((0.0, -outer, c.rim_top / 2.0), (c.patio_half + 2 * c.rim_bar, c.rim_bar, c.rim_top / 2.0)),
            "E": ((outer, 0.0, c.rim_top / 2.0), (c.rim_bar, c.patio_half, c.rim_top / 2.0)),
            "W": ((-outer, 0.0, c.rim_top / 2.0), (c.rim_bar, c.patio_half, c.rim_top / 2.0)),
        }
        UsdGeom.Xform.Define(self.stage, "/World/Rim")
        for name, (pos, scl) in bars.items():
            bar = UsdGeom.Cube.Define(self.stage, f"/World/Rim/Bar_{name}")
            self.set_transform(f"/World/Rim/Bar_{name}", translate=pos, scale=scl)
            self.bind_material(bar.GetPrim(), rim_mat)
            self.add_collider(bar.GetPrim(), dynamic=False)

    def build_path(self):
        """A square dirt path running around the patio, under the ring of trees."""
        c = self.cfg
        if not c.dirt_path:
            return
        mat = self.make_mdl_material("/World/Looks/PathDirt", DIRT_MDL, scale=c.path_tile,
                                     fallback_color=(0.30, 0.22, 0.15))
        rim_edge = c.patio_half + 2 * c.rim_bar
        inner = rim_edge + c.path_inset                 # just outside the curb
        outer = rim_edge + c.tree_gap + c.path_width    # past the tree trunks
        bw = (outer - inner) / 2.0                       # half band width
        mid = (inner + outer) / 2.0
        hz = 0.015
        UsdGeom.Xform.Define(self.stage, "/World/Path")
        bars = {  # N/S span the full outer width (cover corners); E/W fill between them
            "N": ((0.0, mid, hz), (outer, bw, hz)),
            "S": ((0.0, -mid, hz), (outer, bw, hz)),
            "E": ((mid, 0.0, hz), (bw, inner, hz)),
            "W": ((-mid, 0.0, hz), (bw, inner, hz)),
        }
        for name, (pos, scl) in bars.items():
            bar = UsdGeom.Cube.Define(self.stage, f"/World/Path/Bar_{name}")
            self.set_transform(f"/World/Path/Bar_{name}", translate=pos, scale=scl)
            self.bind_material(bar.GetPrim(), mat)

    def place_patio_grid(self):
        """Score the patio into a grid of square tiles (thin dark seam lines), matching ex_imgs."""
        c = self.cfg
        if not c.patio_grid or c.patio_grid_tiles < 2:
            return
        UsdGeom.Xform.Define(self.stage, "/World/PatioGrid")
        mat = self.make_concrete_grey("/World/Looks/PatioSeam", "patio_seam",
                                      c.patio_grid_grey, tile=2.0, roughness=0.95)
        half = c.patio_half
        z = c.patio_top + 0.002
        w = c.patio_grid_w
        step = 2 * half / c.patio_grid_tiles
        idx = 0
        for j in range(1, c.patio_grid_tiles):
            p = -half + j * step
            for axis, (pos, scl) in {
                "x": ((p, 0.0, z), (w, half, 0.004)),   # line running along y at x=p
                "y": ((0.0, p, z), (half, w, 0.004)),   # line running along x at y=p
            }.items():
                seg = UsdGeom.Cube.Define(self.stage, f"/World/PatioGrid/Seam_{idx}_{axis}")
                self.set_transform(f"/World/PatioGrid/Seam_{idx}_{axis}", translate=pos, scale=scl)
                self.bind_material(seg.GetPrim(), mat)
            idx += 1

    def build_lighting(self):
        c = self.cfg
        UsdGeom.Xform.Define(self.stage, "/World/Sky")
        dome = UsdLux.DomeLight.Define(self.stage, "/World/Sky/Dome")
        dome.CreateIntensityAttr(c.dome_intensity)
        dome.CreateColorAttr(Gf.Vec3f(*c.dome_color))
        sun = UsdLux.DistantLight.Define(self.stage, "/World/Sky/Sun")
        sun.CreateIntensityAttr(c.sun_intensity)
        sun.CreateColorAttr(Gf.Vec3f(*c.sun_color))
        sun.CreateAngleAttr(c.sun_angle)
        self.set_transform("/World/Sky/Sun")
        UsdGeom.Xformable(sun.GetPrim()).AddRotateXYZOp().Set(Gf.Vec3f(*c.sun_rot))

    def place_cones(self):
        c = self.cfg
        UsdGeom.Xform.Define(self.stage, "/World/Cones")
        cone_usd = (self.asset_root + CONE_REL) if self.asset_root else None
        h = c.cone_half
        self.cone_xy = []  # remember actual (jittered) cone positions so the boundary can connect them
        for i, (x, y) in enumerate([(h, h), (h, -h), (-h, -h), (-h, h)]):
            jx, jy = self.rng.uniform(-c.cone_jitter, c.cone_jitter, 2)
            px, py = float(x + jx), float(y + jy)
            self.cone_xy.append((px, py))
            path = f"/World/Cones/Cone_{i}"
            if cone_usd is not None:
                prim = add_reference_to_stage(cone_usd, path)
            else:
                UsdGeom.Cone.Define(self.stage, path)
                prim = self.stage.GetPrimAtPath(path)
            self.set_transform(path, translate=(px, py, c.patio_top))
            self.add_collider(prim, dynamic=True)

    def place_boundary(self):
        """Yellow outline connecting the actual cone positions (a vaguely-square loop, like ex_imgs)."""
        c = self.cfg
        pts = getattr(self, "cone_xy", None)
        if not pts:
            h = c.cone_half
            pts = [(h, h), (h, -h), (-h, -h), (-h, h)]
        UsdGeom.Xform.Define(self.stage, "/World/Boundary")
        mat = self.make_emissive("/World/Looks/BoundaryLine", "boundary_line", c.line_color)
        z = c.patio_top + 0.006
        w, t = 0.05, 0.006
        for i in range(len(pts)):
            p0, p1 = pts[i], pts[(i + 1) % len(pts)]
            mxp, myp = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2
            dx, dy = p1[0] - p0[0], p1[1] - p0[1]
            half_len = math.hypot(dx, dy) / 2
            ang = math.degrees(math.atan2(dy, dx))
            path = f"/World/Boundary/Edge_{i}"
            seg = UsdGeom.Cube.Define(self.stage, path)
            self.set_transform(path, translate=(mxp, myp, z), rotate_z=ang, scale=(half_len, w, t))
            self.bind_material(seg.GetPrim(), mat)

    def place_spalls(self):
        c = self.cfg
        pngs = sorted(glob.glob(os.path.join(SPALLS_DIR, "*.png")))
        if not pngs or c.n_spalls <= 0:
            return
        UsdGeom.Xform.Define(self.stage, "/World/Spalls")
        UsdGeom.Scope.Define(self.stage, "/World/Looks/Spalls")
        pick = self.rng.choice(len(pngs), size=min(c.n_spalls, len(pngs)), replace=False)
        for i, idx in enumerate(pick):
            png = pngs[int(idx)]
            half = float(self.rng.uniform(c.spall_half_min, c.spall_half_max))
            x, y = float(self.rng.uniform(-4.5, 4.5)), float(self.rng.uniform(-4.5, 4.5))
            yaw = float(self.rng.uniform(0, 360))
            path = f"/World/Spalls/Spall_{i}"
            self.add_quad(path, half)
            self.set_transform(path, translate=(x, y, c.patio_top + 0.004), rotate_z=yaw)
            mat = self.make_decal(f"/World/Looks/Spalls/Spall_{i}", f"spall_{i}", png, png, 2 * half, 2 * half)
            self.bind_material(self.stage.GetPrimAtPath(path), mat)

    def place_spots(self):
        """A few big, randomly-distributed soft dark stains on the pavement (not tiled speckle)."""
        c = self.cfg
        if c.n_spots <= 0 or not os.path.isfile(SPOT_DIFF):
            return
        UsdGeom.Xform.Define(self.stage, "/World/Spots")
        UsdGeom.Scope.Define(self.stage, "/World/Looks/Spots")
        lim = c.patio_half * 0.82
        for i in range(c.n_spots):
            size = float(self.rng.uniform(1.0, 2.6))      # big, varied
            x, y = float(self.rng.uniform(-lim, lim)), float(self.rng.uniform(-lim, lim))
            yaw = float(self.rng.uniform(0, 360))
            tint = float(self.rng.uniform(0.30, 0.70))    # vary darkness
            path = f"/World/Spots/Spot_{i}"
            self.add_quad(path, 0.5)
            self.set_transform(path, translate=(x, y, c.patio_top + 0.004), rotate_z=yaw, scale=(size, size, 1.0))
            mat = self.make_decal(f"/World/Looks/Spots/Spot_{i}", f"spot_{i}", SPOT_DIFF, SPOT_OPAC,
                                  size, size, threshold=0.0, tint=tint)  # soft alpha-blended stain
            self.bind_material(self.stage.GetPrimAtPath(path), mat)

    def _has_crack(self):
        return os.path.isfile(CRACK_DIFF) and os.path.isfile(CRACK_OPAC)

    def place_cracks(self):
        """Lay the (single) crack PNG flat on the patio: `crack_floor_base` cracks always, plus one
        more with probability `crack_floor_extra_prob`. Kept within the cone-bounds square, random
        orientation, scaled to a few metres like ex_imgs."""
        c = self.cfg
        if not self._has_crack():
            return
        from PIL import Image
        w, h = Image.open(CRACK_OPAC).size
        n = c.crack_floor_base + (1 if self.rng.uniform() < c.crack_floor_extra_prob else 0)
        UsdGeom.Xform.Define(self.stage, "/World/Cracks")
        UsdGeom.Scope.Define(self.stage, "/World/Looks/Cracks")
        for i in range(n):
            L = float(self.rng.uniform(c.crack_len_min, c.crack_len_max))   # long axis
            sx, sy = (L * w / h, L) if h >= w else (L, L * h / w)           # preserve aspect
            lim = max(0.3, c.cone_half - 0.5 * max(sx, sy))                 # stay within cone bounds
            x, y = float(self.rng.uniform(-lim, lim)), float(self.rng.uniform(-lim, lim))
            yaw = float(self.rng.uniform(0, 360))
            path = f"/World/Cracks/Crack_{i}"
            self.add_quad(path, 0.5)
            self.set_transform(path, translate=(x, y, c.patio_top + 0.005), rotate_z=yaw, scale=(sx, sy, 1.0))
            mat = self.make_decal(f"/World/Looks/Cracks/Crack_{i}", f"crack_{i}", CRACK_DIFF, CRACK_OPAC,
                                  sx, sy, threshold=0.3, tint=c.crack_tint)
            self.bind_material(self.stage.GetPrimAtPath(path), mat)

    def place_pillar_crack(self):
        """With probability `crack_pillar_prob`, stick the crack PNG vertically on the column's side."""
        c = self.cfg
        if not self._has_crack() or self.rng.uniform() >= c.crack_pillar_prob:
            return
        px, py = getattr(self, "pillar_xy", (0.0, 0.0))
        R = c.pillar_radius + 0.012
        theta = float(self.rng.uniform(0, 360))
        a = math.radians(theta)
        height = float(self.rng.uniform(0.9, 1.3))
        width = height  # square quad; the crack sits centered (thin) within it
        z_c = c.patio_top + c.pillar_height * 0.5
        path = "/World/Cracks/PillarCrack"
        UsdGeom.Xform.Define(self.stage, "/World/Cracks")
        self.add_quad(path, 0.5)
        xf = UsdGeom.Xformable(self.stage.GetPrimAtPath(path))
        xf.ClearXformOpOrder()
        xf.AddTranslateOp().Set(Gf.Vec3d(px + R * math.cos(a), py + R * math.sin(a), z_c))
        xf.AddRotateZOp().Set(theta - 90.0)   # face outward at azimuth theta
        xf.AddRotateXOp().Set(-90.0)          # stand the quad upright
        xf.AddScaleOp().Set(Gf.Vec3f(width, height, 1.0))
        mat = self.make_decal("/World/Looks/Cracks/PillarCrack", "pillar_crack", CRACK_DIFF, CRACK_OPAC,
                              width, height, threshold=0.3, tint=c.crack_tint)
        self.bind_material(self.stage.GetPrimAtPath(path), mat)

    def _sample_free(self, place_r, rad, margin=0.25, tries=400):
        """Sample (x,y) in a disk (radius place_r) that keeps a circle of `rad` clear of every
        already-placed obstacle in self.obstacles (each (x,y,radius))."""
        obs = getattr(self, "obstacles", [])
        last = (0.0, 0.0)
        for _ in range(tries):
            a = self.rng.uniform(0, 2 * math.pi)
            rr = place_r * math.sqrt(self.rng.uniform(0, 1))
            x, y = rr * math.cos(a), rr * math.sin(a)
            last = (x, y)
            if all(math.hypot(x - ox, y - oy) >= rad + orr + margin for ox, oy, orr in obs):
                return x, y
        return last  # best effort if crowded

    def place_barriers(self):
        c = self.cfg
        if not os.path.isfile(BARRIER_USD):
            print(f"[warn] barrier asset missing at {BARRIER_USD}")
            return
        UsdGeom.Xform.Define(self.stage, "/World/Barriers")
        self.obstacles = getattr(self, "obstacles", [])
        bbox = UsdGeom.BBoxCache(Usd.TimeCode.Default(),
                                 [UsdGeom.Tokens.default_, UsdGeom.Tokens.render])
        barrier_r = None
        for i in range(c.n_barriers):
            path = f"/World/Barriers/Barrier_{i}"
            prim = add_reference_to_stage(BARRIER_USD, path)
            yaw = float(self.rng.uniform(0.0, 360.0))
            if barrier_r is None:  # measure the barrier's bounding radius once (yaw-invariant half-diagonal)
                self.set_transform(path, translate=(0.0, 0.0, 0.0), scale=(c.barrier_scale,) * 3)
                bbox.Clear()
                b = bbox.ComputeWorldBound(prim).ComputeAlignedRange()
                mn, mx = b.GetMin(), b.GetMax()
                barrier_r = 0.5 * math.hypot(mx[0] - mn[0], mx[1] - mn[1]) or 0.8
            place_r = max(0.3, c.cone_half - barrier_r - 0.1)
            x, y = self._sample_free(place_r, barrier_r)
            self.obstacles.append((x, y, barrier_r))
            self.set_transform(path, translate=(float(x), float(y), c.patio_top), rotate_z=yaw,
                               scale=(c.barrier_scale,) * 3)
            if c.barrier_grey > 0:  # asset's own diffuse is a brick-like collage; use rugged concrete
                grey = self.make_concrete_grey(f"/World/Looks/Barrier_{i}", f"barrier_{i}",
                                               c.barrier_grey, tile=c.barrier_tile, roughness=0.9,
                                               normal_tex=GRAVEL_NOR, rough_tex=GRAVEL_ROUGH,
                                               albedo_noise_tex=CONCRETE_NOISE)
                self.bind_material_all(prim, grey)
            else:
                self.convert_to_omnipbr(prim, f"{path}/_omnipbr", os.path.dirname(BARRIER_USD))
            self.add_collider(prim, dynamic=False)

    def place_pillar(self):
        c = self.cfg
        pillar_r = c.pillar_radius + 0.15
        place_r = max(0.3, c.cone_half - pillar_r - 0.1)
        x, y = self._sample_free(place_r, pillar_r)  # never overlap the barriers
        self.obstacles = getattr(self, "obstacles", []) + [(x, y, pillar_r)]
        self.pillar_xy = (x, y)
        cyl = UsdGeom.Cylinder.Define(self.stage, "/World/Pillar")
        cyl.CreateRadiusAttr(c.pillar_radius)
        cyl.CreateHeightAttr(c.pillar_height)
        cyl.CreateAxisAttr(UsdGeom.Tokens.z)
        self.set_transform("/World/Pillar", translate=(x, y, c.patio_top + c.pillar_height / 2.0))
        # rugged grey concrete (strong relief + imperfection blotches)
        self.bind_material(cyl.GetPrim(),
                           self.make_concrete_grey("/World/Looks/PillarConcrete", "pillar_concrete",
                                                   c.pillar_grey, tile=c.pillar_tile, roughness=0.85,
                                                   normal_tex=GRAVEL_NOR, rough_tex=GRAVEL_ROUGH,
                                                   albedo_noise_tex=CONCRETE_NOISE))
        self.add_collider(cyl.GetPrim(), dynamic=False)

    def _collapse_to_single_tree(self, root):
        groups = [c for c in root.GetChildren()
                  if c.GetName() != "_materials" and any(d.IsA(UsdGeom.Mesh) for d in Usd.PrimRange(c))]
        if len(groups) > 1:
            keep = groups[int(self.rng.integers(len(groups)))]
            for g in groups:
                if g is not keep:
                    g.SetActive(False)
            return keep.GetName()
        return groups[0].GetName() if groups else None

    def _tree_pool(self):
        pool = []
        if self.asset_root is not None:
            for name in self.cfg.isaac_trees:
                pool.append((self.asset_root + VEG_TREE_REL.format(name), False, None))
        if self.cfg.use_local_trees:
            for p in TREE_USDS:
                if os.path.isfile(p):
                    pool.append((p, True, os.path.dirname(p)))
        return pool

    def place_trees(self):
        c = self.cfg
        pool = self._tree_pool()
        if not pool:
            print("[warn] no tree assets found; skipping trees")
            return
        UsdGeom.Xform.Define(self.stage, "/World/Trees")
        bbox = UsdGeom.BBoxCache(Usd.TimeCode.Default(),
                                 [UsdGeom.Tokens.default_, UsdGeom.Tokens.render])
        n = max(1, c.n_trees)
        rim_edge = c.patio_half + 2 * c.rim_bar
        order = self.rng.permutation(len(pool))
        for i in range(n):
            ang = (360.0 / n) * i + float(self.rng.uniform(-8, 8))
            a = math.radians(ang)
            usd, needs_convert, asset_dir = pool[order[i % len(pool)]]
            path = f"/World/Trees/Tree_{i}"
            prim = add_reference_to_stage(usd, path)
            if needs_convert:
                self._collapse_to_single_tree(self.stage.GetPrimAtPath(path))
            yaw = float(self.rng.uniform(0, 360))
            # measure at unit scale, normalize height -> caps size AND fixes cm-vs-m unit mismatch
            self.set_transform(path, translate=(0.0, 0.0, 0.0), rotate_z=yaw, scale=(1.0, 1.0, 1.0))
            bbox.Clear()
            b = bbox.ComputeWorldBound(prim).ComputeAlignedRange()
            mn, mx = b.GetMin(), b.GetMax()
            height = mx[2] - mn[2]
            if height <= 1e-6:
                continue
            k = float(self.rng.uniform(c.tree_h_min, c.tree_h_max)) / height
            cx, cy, mnz = (mn[0] + mx[0]) / 2 * k, (mn[1] + mx[1]) / 2 * k, mn[2] * k
            rim_dist = rim_edge / max(abs(math.cos(a)), abs(math.sin(a)))
            r_trunk = rim_dist + c.tree_gap
            tx, ty = r_trunk * math.cos(a) - cx, r_trunk * math.sin(a) - cy
            self.set_transform(path, translate=(tx, ty, -mnz), rotate_z=yaw, scale=(k, k, k))
            if needs_convert:
                self.convert_to_omnipbr(prim, f"{path}/_omnipbr", asset_dir)

    def build(self):
        self.build_physics()
        self.build_ground()
        self.build_path()
        self.place_patio_grid()
        self.build_lighting()
        self.place_cones()
        self.place_boundary()
        self.place_spalls()
        self.place_spots()
        self.place_cracks()
        self.place_barriers()
        self.place_pillar()
        self.place_pillar_crack()
        self.place_trees()
