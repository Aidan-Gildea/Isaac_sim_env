# LEARN.md — The Complete Walkthrough

*A single-file study guide for the inspection-plaza environment generator. Starts from zero
Isaac Sim knowledge and works up to every design decision in the codebase. Code excerpts are
quoted from the actual project files (open them side-by-side in VSCode; function names are
given so you can jump with `Ctrl+Shift+O`). This file is gitignored — it's your private
study copy.*

**How to study this:** read Part 1 for the map, Part 2 slowly (it's the foundation everything
else stands on), Part 3 with the real files open, Part 4 as stories (they're the best interview
material), then drill Part 6 until you can answer without looking.

---

## Part 1 — The 30,000-foot view

### What this project is

A **procedural environment generator**: a Python program that *builds* a 3D world — an
"infrastructure inspection plaza" (concrete patio, jersey barriers, a cracked stone column,
traffic cones, a yellow boundary, damage marks, trees) — and saves it as a `.usd` file that
Isaac Sim can open, render, and simulate physics in. Every build is controlled by a **config**
(a list of ~50 numbers/flags) and a **random seed**, so:

- the same seed + config always produces the *identical* scene (reproducibility), and
- changing the seed produces a *variant* — same recipe, different layout (domain randomization).

The end goal (per `PROJECT_PLAN.md`) is a *set* of such variants for training robot policies
by imitation learning: a robot that must learn "inspect the plaza" shouldn't overfit to one
exact arrangement of barriers, one lighting condition, one crack position.

### The pipeline, in one diagram

```
scene_config.py          scene_lib.py              USD stage            outputs
┌──────────────┐  load  ┌────────────────┐ author ┌──────────┐ export ┌──────────────────┐
│ SceneConfig  │ ─────► │  SceneBuilder  │ ─────► │ /World/… │ ─────► │ out/iter_NNN.usd │
│ (JSON knobs) │        │  .build()      │        │  prims   │        └────────┬─────────┘
└──────────────┘        └────────────────┘        └──────────┘                 │ open
        ▲                                                          ┌───────────┴───────────┐
        │ edit knobs, re-run                                       ▼                       ▼
        │                                                 launch_scene.py          render_scene.py /
        └───────────────── compare renders ◄───────────── (interactive GUI)        render_views.py
                           to ex_imgs/                                              (headless PNGs)
```

Two entry points share **one** scene definition (`scene_lib.py`). That's deliberate: if the GUI
built the scene one way and the renderer another, you could never trust that what you tuned is
what you captured.

### Repo map (what to study vs. skim)

| Path | What it is | Study depth |
|---|---|---|
| `scene_config.py` | All tunable knobs (dataclass ↔ JSON) | **Deep** — it's the project's vocabulary |
| `scene_lib.py` | The builder: geometry, materials, physics, randomization | **Deep** — the heart |
| `launch_scene.py` | GUI entry point | Medium (short file, one trick) |
| `render_scene.py` | Headless single-shot renderer | Medium (exposure + camera) |
| `render_views.py` | 5-angle render pass per iteration | Medium |
| `AUTOMATION.md` | The iterate→render→compare→commit loop rules | Read once |
| `PROJECT_PLAN.md` | The original full-project plan (batch generation etc.) | Read once |
| `configs/iter_NNN.json` | One config snapshot per iteration | Skim (it's data) |
| `out/*.usd` | Saved stages (the actual environments) | Data |
| `finals/`, `screenshots/` | Rendered evidence per iteration | Data |
| `assets/textures/*` | *Generated* noise/gravel/crack maps (by our scripts) | Know what each is |
| `assets/{trees,barriers}/` | Downloaded Poly-Haven/Blender assets | Data |
| `cracks/`, `Spalls/`, `ex_imgs/` | Your inputs: crack PNG, spall PNGs, reference photos | Data |
| `inspect_*.py`, `discover*.py`, `probe*.py` | One-off measurement/diagnosis scripts | Skim — but know *why* they exist (Part 4) |
| `models/` | Original asset zips | Ignore |

---

## Part 2 — Fundamentals (from zero)

### 2.1 What Isaac Sim actually is

**Isaac Sim** is NVIDIA's robotics simulator. It's built on **Omniverse Kit** — a modular
application platform where everything (the viewport, the physics engine, the file browser) is
an *extension*. Three subsystems matter to us:

1. **USD** (Universal Scene Description, from Pixar) — the scene *data model*. Everything in a
   scene — meshes, lights, materials, physics flags — is data in a USD "stage". This is the part
   we author.
2. **RTX renderer** — path-traced/ray-traced rendering of that stage. We only *configure* it
   (exposure, materials); we never touch rendering code.
3. **PhysX** — the physics engine. It reads physics *schemas* we attach to prims (see 2.4) and
   simulates when you press Play.

**The `SimulationApp` rule.** Isaac Sim is not a library you casually import — it's an
application you boot. Every script in this project starts:

```python
from isaacsim import SimulationApp
sim_app = SimulationApp({"headless": True})      # boots Omniverse Kit (~30-60s)
# ONLY NOW may you import omni.*, pxr.*, isaacsim.core.* ...
import omni.usd
from pxr import UsdGeom
```

Importing `pxr`/`omni` *before* creating `SimulationApp` crashes or misbehaves, because those
modules are provided by the running Kit app. This is why `scene_lib.py`'s docstring warns:
*"Import this ONLY after a SimulationApp has been created."* It's also why every entry script
parses `argparse` args *first* (cheap), then boots the app (expensive).

`headless=True` runs without a window (for rendering/inspection scripts — faster, scriptable);
`headless=False` opens the full GUI (what you use to fly around). The GUI's main loop is
literally ours to run:

```python
# launch_scene.py (end)
while sim_app.is_running():
    sim_app.update()          # one frame: process UI, render, tick
sim_app.close()
```

### 2.2 USD — the scene as a document

Think of a USD **stage** as an XML-like document describing a scene tree. The nodes are
**prims** (primitives), each with a **path** like a filesystem:

```
/World                      ← an Xform (a transform grouping node)
/World/Patio                ← a Cube prim
/World/Barriers/Barrier_0   ← an Xform that references an external file
/World/Looks/PatioConcrete  ← a Material prim
```

Key vocabulary, all of which appears in our code:

- **Prim**: one node. Has a *type* (`Cube`, `Mesh`, `Xform`, `Material`, `DistantLight`...).
- **Attribute**: a typed value on a prim (`radius`, `points`, `intensity`). In code:
  `cyl.CreateRadiusAttr(0.22)` or generic `prim.CreateAttribute(name, type).Set(value)`.
- **Define**: create-or-get a prim of a type at a path:
  `UsdGeom.Cube.Define(stage, "/World/Patio")`.
- **defaultPrim**: which top-level prim represents "the scene" when this file is referenced
  from elsewhere. We set `/World` in `SceneBuilder.__init__`.
- **Reference**: include another USD file *inside* this stage at some path — how we bring in
  the traffic cone, barrier and tree assets without copying their data:
  `add_reference_to_stage(usd_path, "/World/Cones/Cone_0")`.
- **Export**: write the current stage to a file: `stage.GetRootLayer().Export("out/x.usd")`.

**Units and orientation** — first thing `SceneBuilder.__init__` does:

```python
UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)   # Z is "up" (robotics convention)
UsdGeom.SetStageMetersPerUnit(stage, 1.0)         # 1 unit = 1 meter
```

This matters enormously: USD files each declare their *own* units. The NVIDIA tree assets are
authored in **centimeters** (`metersPerUnit=0.01`); referencing them into our meters stage does
**not** auto-convert, so an un-corrected tree is 100× too big. (War story #2, and the reason
`place_trees` measures and rescales every tree.)

**Transforms and xformOps.** A prim's placement is a *list of transform operations* applied in
order. Our helper authors a canonical order:

```python
# scene_lib.py — set_transform()
xf = UsdGeom.Xformable(self.stage.GetPrimAtPath(prim_path))
xf.ClearXformOpOrder()                    # wipe whatever was there
xf.AddTranslateOp().Set(Gf.Vec3d(*translate))
if rotate_z:
    xf.AddRotateZOp().Set(float(rotate_z))
if scale is not None:
    xf.AddScaleOp().Set(Gf.Vec3f(*scale))
```

Order matters: this list means "scale the object, then rotate it, then move it" (ops apply to
points right-to-left). Also note the types: translate is `Vec3d` (double), scale `Vec3f`
(float). USD is strict — an existing `double3` scale op clashes with adding a `float3` one,
which is why `add_quad()` strips the xformOps that Kit's plane-creation command authors before
adding ours (that exact clash once crashed a build).

**Bounding boxes.** `UsdGeom.BBoxCache.ComputeWorldBound(prim)` returns the prim's world-space
box. We use it to *measure* assets we didn't author (tree sizes, crack footprints) instead of
trusting guesses — a recurring theme: **measure, don't assume**.

### 2.3 Materials — how things get their look

USD materials are little node graphs under a `Material` prim: a `Shader` node with **inputs**
(colors, texture file paths, flags), connected to the material's output. Binding attaches a
material to geometry:

```python
# scene_lib.py — bind_material()
mat = UsdShade.Material(self.stage.GetPrimAtPath(mat_path))
UsdShade.MaterialBindingAPI.Apply(prim)
UsdShade.MaterialBindingAPI(prim).Bind(mat)
```

Three material *languages* appear in this project:

1. **UsdPreviewSurface** — USD's portable standard shader. Blender exports use it. **The RTX
   renderer shows it as flat red** (unsupported wiring), which is why every downloaded asset
   (barriers, trees) initially rendered red — War story #1.
2. **MDL** (NVIDIA's Material Definition Language) — what RTX natively speaks. The Omniverse
   asset library ships `.mdl` materials (e.g. `Masonry/Concrete_Rough.mdl`); `make_mdl_material`
   wires one up by URL:

```python
# scene_lib.py — make_mdl_material()
shader.SetSourceAsset(Sdf.AssetPath(url), "mdl")
shader.SetSourceAssetSubIdentifier(mtl_name, "mdl")
mat.CreateSurfaceOutput("mdl").ConnectToSource(shader.ConnectableAPI(), "out")
```

3. **OmniPBR** — NVIDIA's general-purpose MDL shader, created via the convenience class
   `isaacsim.core.api.materials.OmniPBR`. Nearly every custom material here is OmniPBR with
   inputs set manually:
   - `diffuse_color_constant` — flat base color
   - `texture_path` / diffuse texture — an image as base color
   - `diffuse_tint` — multiplies the diffuse (used to darken without changing texture)
   - `normalmap_texture` — fake surface bumps from an image (lighting responds, geometry doesn't)
   - `reflectionroughness_texture`, `reflection_roughness_constant` — how shiny/matte
   - `enable_opacity`, `opacity_texture`, `opacity_threshold` — cut-out transparency (see below)
   - `enable_emission`, `emissive_color/intensity` — self-glowing (the yellow boundary line)
   - `project_uvw` — **triplanar projection** (next paragraph)

**UV mapping vs. triplanar.** A texture needs a rule for wrapping onto geometry. Meshes can
carry **UV coordinates** (a `primvars:st` attribute: each vertex knows its (u,v) spot in the
image). Primitive shapes we `Define()` (Cube, Cylinder) have *no* UVs — so for them we set
`project_uvw=True`, which projects the texture along the object's axes ("triplanar"), with
`texture_scale` controlling tiling. Rule of thumb in this codebase:

- Big surfaces (floor, patio, rim, pillar body): **triplanar** — seamless tiling, no UVs needed.
- Precise image placement (a decal that must sit exactly on a quad): **mesh UVs** — the image
  is pinned to the geometry and cannot swim/flip with the camera (War story #6).

**Opacity cut-outs.** `opacity_texture` takes a **grayscale mask** (white = keep, black =
invisible). Crucial subtlety we learned the hard way: OmniPBR reads a *mono* value, not a PNG's
alpha channel — so decals need *two* images (color + separate mask), and RGBA alpha alone gets
misread (part of War story #5). Tree leaves work the same way: the leaf texture + an 8-bit
grayscale alpha copy.

**GeomSubsets.** One mesh can have *per-face* material assignments — a tree is a single mesh
whose trunk faces bind bark and leaf faces bind foliage, via child `GeomSubset` prims. Any code
that re-binds materials must walk subsets too, or you fix the trunk and leave the leaves red:

```python
# scene_lib.py — convert_to_omnipbr(), the traversal
if tn in ("Mesh", "GeomSubset"):
    bm, _ = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
```

**sRGB vs. linear color** (bit us once, worth knowing): image files store *gamma-encoded* sRGB
values; the renderer computes in *linear* light. A pixel value 0.19 in a texture is **not** 19%
brightness — it's decoded to ~0.03 linear (near-black). Numeric shader inputs like
`diffuse_tint` are already linear. Baking `0.19 × texture` into a PNG without re-encoding
(`value^(1/2.2)`) produced an almost-black pillar — War story #7.

### 2.4 Physics — schemas on top of geometry

USD separates *what things look like* from *how they behave*. Physics is added by **applying
API schemas** to existing prims:

```python
# scene_lib.py — add_collider()
UsdPhysics.CollisionAPI.Apply(prim)                     # this prim blocks things
UsdPhysics.MeshCollisionAPI.Apply(child).CreateApproximationAttr().Set("convexHull")
if dynamic:
    UsdPhysics.RigidBodyAPI.Apply(prim)                 # gravity moves it
    UsdPhysics.MassAPI.Apply(prim)
```

The taxonomy used in this scene:

| Object | Physics | Why |
|---|---|---|
| Floor, patio, rim, barriers, pillar | **Static collider** (CollisionAPI only) | Immovable obstacles |
| Cones | **Dynamic rigid body** (+RigidBodyAPI/MassAPI) | Knock-over-able by a robot |
| Trees, decals, crack ribbons | **No physics** | Decoration; zero sim cost |

`approximation="convexHull"` tells PhysX to wrap the mesh in a convex shell instead of using
raw triangles — dynamic bodies *require* a convex (or primitive) shape; the console warning
about cones "falling back to convexHull" is PhysX telling us it did this automatically.
`build_physics()` creates the one `UsdPhysics.Scene` with gravity (0,0,-1) × 9.81.

### 2.5 Headless rendering — how the PNGs get made

The GUI renders to a window; scripts need pixels in memory. That's **Replicator**
(`omni.replicator.core`), Isaac Sim's synthetic-data toolkit:

```python
# render_scene.py — the capture rig
cam = rep.create.camera(position=..., look_at=..., focal_length=...)
rp  = rep.create.render_product(cam, (1024, 576))     # camera + resolution = a render target
ann = rep.AnnotatorRegistry.get_annotator("rgb")      # "give me color pixels"
ann.attach([rp])
...
rep.orchestrator.step(rt_subframes=24)                # render, accumulating 24 subframes
arr = np.asarray(ann.get_data())                      # H×W×4 numpy array
```

(`rt_subframes` = how many samples RTX accumulates per frame — more = less noise.)
Annotators are a family — `"rgb"` here, but the same rig yields depth/segmentation later for
robot training data.

Two hard-won render-quality rules live at the top of `render_scene.py`/`render_views.py`:

```python
_settings.set_bool("/rtx/post/histogram/enabled", False)  # no auto-exposure
_settings.set_int("/rtx/post/tonemap/op", 1)              # ACES filmic tonemap
_settings.set_float("/rtx/post/tonemap/filmIso", 100.0)   # FIXED exposure
```

Auto-exposure re-brightens every shot based on content — good for eyeballs, fatal for
*comparing* iterations or matching specific grey values (a material change and an exposure
change look identical). Fixing exposure makes albedo → pixel value deterministic (War story #4).

And the strangest one — **the export/reopen trick**:

```python
# render_scene.py (and launch_scene.py)
stage.GetRootLayer().Export(out_usd)
omni.usd.get_context().open_stage(out_usd)   # reopen the file we just wrote
```

Building a scene *live* (referencing many heavy tree assets into the open stage) left most
trees invisible to the renderer — the render index (Hydra) never synced them. Saving the stage
to disk and reopening forces a clean load where everything renders. Empirical fix, applied at
every entry point (War story #3).

### 2.6 Randomization done right

One generator object, seeded once, used *everywhere*:

```python
self.rng = np.random.default_rng(cfg.seed)     # SceneBuilder.__init__
```

Same seed ⇒ same sequence of draws ⇒ same scene, which makes bugs reproducible ("seed 4 shows
the pillar crack") and datasets auditable. Corollary: the *number and order* of `rng` calls is
part of the contract — inserting a draw early in `build()` shifts every random outcome after
it. We hit this: changing crack placement changed which seeds spawn the pillar crack.

**Rejection sampling** is the placement workhorse — sample candidates until constraints hold:

```python
# scene_lib.py — _sample_free(): random point keeping `rad` clear of all obstacles
for _ in range(tries):
    a  = self.rng.uniform(0, 2 * math.pi)
    rr = place_r * math.sqrt(self.rng.uniform(0, 1))   # sqrt → uniform over the DISK's area
    x, y = rr * math.cos(a), rr * math.sin(a)
    if all(math.hypot(x - ox, y - oy) >= rad + orr + margin for ox, oy, orr in obs):
        return x, y
```

(The `sqrt` detail: sampling radius uniformly would cluster points near the center; area grows
as r², so take √ of a uniform draw.) Barriers and pillar register themselves in
`self.obstacles` so nothing overlaps; floor cracks use the same idea with `crack_min_sep`.

---

## Part 3 — File-by-file walkthrough

### 3.1 `scene_config.py` — the vocabulary of the scene

One `@dataclass` holding every knob, with JSON round-tripping. Two design points to internalize:

```python
@dataclass
class SceneConfig:
    seed: int = 0
    patio_half: float = 7.0        # half-side: the patio is 14 m × 14 m
    patio_top: float = 0.10        # patio top is 10 cm above the floor (floor top = z 0)
    ...
    @classmethod
    def from_dict(cls, d: dict) -> "SceneConfig":
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})
```

- **No Isaac imports.** The config can be loaded/edited anywhere (a laptop, a CI job) without
  booting the simulator. Separation of *description* from *execution*.
- **`from_dict` filters unknown keys.** Old iteration JSONs (missing newer fields, or having
  removed ones) still load — new fields fall back to defaults. That's what makes 40+ config
  snapshots in `configs/` forward-compatible.
- **Halves, not fulls.** Sizes are half-extents (`patio_half=7` → 14 m side) because USD's
  `Cube` is 2 units across, so a scale of `h` gives a side of `2h`. Heights are absolute z
  ("patio top at 0.10 m") — the layering floor(0) < patio(0.10) < rim(0.22) is the plaza's
  vertical anatomy.

The knob groups (read the file alongside): layout (`*_half`, `rim_*`), surface materials
(`*_grey` [0..1 reflectance], `*_tile` [triplanar repeat], `*_rough`), the scored tile grid
(`patio_grid_*`), obstacles (`cone_*`, `barrier_*`, `pillar_*`), damage (`n_spalls`, `n_spots`,
`crack_*`), trees (`n_trees`, `tree_h_*`, `isaac_trees` — names under
`/NVIDIA/Assets/Vegetation/Trees`), lighting (`dome_*` ambient sky, `sun_*` directional), and
the capture camera (`cam_pos/look/focal`, `res_*`).

`if __name__ == "__main__"` writes `configs/base.json` — run it after adding a field.

### 3.2 `scene_lib.py` — the heart (read in `build()` order)

At the bottom, `build()` is the table of contents:

```python
def build(self):
    self.build_physics()      # gravity + physics scene
    self.build_ground()       # floor, patio, rim
    self.build_path()         # optional dirt ring (off in current configs)
    self.place_patio_grid()   # scored tile seams
    self.build_lighting()     # dome sky + sun
    self.place_cones()        # 4 corners, jittered; remembers positions
    self.place_boundary()     # yellow line connecting the actual cones
    self.place_spalls()       # spall PNG decals (n_spalls, currently 0)
    self.place_spots()        # dark stain decals (n_spots, currently 0)
    self.place_cracks()       # floor cracks — GEOMETRY ribbons from the crack PNG
    self.place_barriers()     # referenced asset, non-overlap sampling
    self.place_pillar()       # mesh cylinder (not analytic!) + concrete material
    self.place_pillar_crack() # geometry ribbon ON the column surface
    self.place_trees()        # measured, height-normalized ring outside the rim
```

#### The constructor

```python
def __init__(self, stage, cfg, asset_root=None):
    self.stage = stage
    self.cfg = cfg
    self.asset_root = asset_root if asset_root is not None else get_asset_root()
    self.rng = np.random.default_rng(cfg.seed)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(stage.GetPrimAtPath("/World"))
```

`asset_root` is the URL of NVIDIA's cloud asset library (found via
`isaacsim.storage.native.get_assets_root_path()`); cones, MDL concretes, and library trees are
fetched from it. If it's unreachable, material helpers fall back to flat grey OmniPBR — the
build *degrades*, never crashes (see the `try/except` in `make_mdl_material`).

#### Material helpers (all covered conceptually in §2.3 — map them):

- `make_omnipbr` — flat color.
- `make_emissive` — flat color + glow (the boundary line: emission makes it readable even in shadow).
- `make_concrete_grey` — *the* ground-surface material. Exact grey (either as
  `diffuse_color_constant`, or as noise-texture × `diffuse_tint` where tint = grey/0.9 because
  the noise texture's mean is 0.9 — that keeps the *average* color exact while adding grain),
  plus triplanar normal/roughness maps for relief.
- `make_decal` — diffuse image + **separate grayscale mask** via mesh UVs (never triplanar —
  that's the flip bug), `opacity_threshold` for hard cut-outs vs `0.0` for soft blends.
- `make_mdl_material` — library MDL by (category, name), e.g. `("Natural", "Dirt")`.
- `convert_to_omnipbr` — the Blender-asset fixer (War story #1): walks the referenced asset,
  *traces* each UsdPreviewSurface input through its node graph to find the actual texture file
  (`_texture_of` → `_find_uvtex_file`, a recursive connection-follower), builds an equivalent
  OmniPBR, and rebinds **meshes and GeomSubsets**. Returns how many materials it converted.

#### Geometry helpers

- `add_quad` — creates Kit's **Plane** prim (via `omni.kit.commands.execute(
  "CreateMeshPrimWithDefaultXform", prim_type="Plane", ...)`) rather than hand-authoring a
  4-vertex mesh. Reason: the command's plane carries `st` UVs in exactly the form RTX samples
  correctly; our hand-built quad's UVs read as a single texel (invisible decals). It then
  strips the command's double-precision xformOps to avoid the float/double clash.
- `add_collider` — §2.4.

#### Scene parts worth knowing cold

**`build_ground`** — three layers of `Cube` prims: floor (60×60 m, top at z=0), patio
(raised, top at `patio_top`), rim (4 bars framing the patio, higher still). All static
colliders. Note how a "slab" is just a cube scaled thin, positioned so its *top* lands at the
right z (translate z = height/2).

**`place_patio_grid`** — the scored-tile look is (tiles-1) thin dark cubes laid across the
patio in each axis at `z = patio_top + 0.002`. Cheap, and it never z-fights because 2 mm is
above the surface but visually "on" it.

**`build_lighting`** — two lights: a `DomeLight` (the sky — light from everywhere, sets
ambient level and color) and a `DistantLight` (the sun — parallel rays; `angle` is its angular
diameter, bigger = softer shadows). The sun's direction is an XYZ euler rotation. Warm sun +
cool-ish dome is the current look.

**`place_cones` + `place_boundary`** — cones go at the four corners of a `cone_half` square,
each jittered by ±`cone_jitter` ("vaguely square", per the reference photos). Crucially the
*actual* jittered positions are remembered (`self.cone_xy`) and the boundary draws four thin
emissive boxes connecting them — each segment's midpoint/length/angle computed with
`atan2`/`hypot`. Boundary follows cones; they can never disagree.

**`place_spalls` / `place_spots`** — decal quads on the patio (spall PNGs as their own mask;
spots use a generated soft radial mask with `threshold=0.0` for soft edges). Both currently 0
in the config — the spots visually read as "extra cracks" and were cut.

**Floor cracks — `_crack_path` + `_crack_ribbon` + `place_cracks`.** The design that survived
five failed approaches (War story #5): cracks are **opaque geometry**, and their shape comes
**from your PNG**:

```python
# _crack_path(): PNG → (t, offset, width) samples
m = a > 120                                  # threshold the alpha into a mask
# ... BFS flood-fill labels connected components; keep the LARGEST one
rows = [(y, xs.mean(), xs.size) for y in range(H) ...]   # per-row: center x, thickness
off = (interp(...) - mean) / span            # lateral deviation, normalized by crack length
wid = interp(...) / span                     # local width, normalized
```

Why largest-component-only: the photo's crack has disconnected fragments; rendered small, each
quad showed "2–3 marks" that read as *pairs of cracks*. One component = one continuous crack.

```python
# _crack_ribbon(): samples → a flat triangle-strip ribbon
cxk = origin[0] + t[k]*L*dx + off[k]*L*nx_    # walk the heading, deviate laterally
w   = max(min_w, wid[k] * L * width_scale)    # PNG's width profile, scaled
pts.append(...center - perp*w/2...); pts.append(...center + perp*w/2...)
# pairs of points → quad strip; subdivisionScheme=none; doubleSided; doNotCastShadows
```

`primvars:doNotCastShadows` matters: a decal 1–8 mm above the ground casts a thin drop shadow
that renders as a *twin* of itself (that was the "cracks travel in pairs" + "floating" report).
`place_cracks` draws the count (`crack_floor_base` + one more with probability
`crack_floor_extra_prob`), rejection-samples positions with `crack_min_sep`, keeps every crack
inside the cone square, and randomizes heading/length/mirror/reverse so instances differ.
Material: near-black, `reflection_roughness_constant=1.0`, `specular_level=0.0` — without
that, one crack caught the warm sun's specular and rendered *tan*.

**`place_barriers`** — references the barrier asset per instance, measures its footprint
radius **once** via `BBoxCache` (half the bbox diagonal — yaw-safe), then `_sample_free`
placement so barriers never overlap each other or the pillar. `barrier_grey > 0` overrides the
asset's own texture (a brick-like collage — looked wrong) with rugged grey concrete via
`bind_material_all`.

**`place_pillar`** — the column is a **mesh** cylinder created by the Kit command, *not*
`UsdGeom.Cylinder`. The analytic cylinder is a mathematical surface RTX intersects exactly —
and alpha-cutout decals within millimeters of it misrender (invisible/foggy). Mesh geometry
behaves. The pillar registers itself as an obstacle and stores `self.pillar_xy` for the crack.

**`place_pillar_crack`** — with probability `crack_pillar_prob`, a jagged ribbon whose
vertices are computed **on the cylinder surface**:

```python
a += math.radians(self.rng.uniform(-14, 14))       # azimuth wanders per step
da = (w / 2.0) / R                                  # half-width as an ANGLE on the surface
pts.append(Gf.Vec3f(px + R*cos(a±da), py + R*sin(a±da), z_k))
```

Because every vertex sits at radius R+1 mm, the crack *cannot* float or detach at any viewing
angle — it is part of the surface by construction. (The PNG-path version was tried here too:
its wide lateral swings, wrapped onto a 22 cm-radius column, folded the ribbon into loops — so
the pillar keeps the random-wander path, which you approved visually.)

**`place_trees`** — three sub-problems, each a war story:
1. *The pool* (`_tree_pool`): NVIDIA library trees (already MDL-textured — no conversion
   needed) + your local Blender trees (need `convert_to_omnipbr`).
2. *Cluster collapse* (`_collapse_to_single_tree`): `fir_sapling_medium.usdc` is secretly a
   ~15 m *cluster* of three saplings; keep one subtree, `SetActive(False)` the rest.
3. *Height normalization*: reference each tree, measure its bbox at scale 1, then scale so its
   height lands in `[tree_h_min, tree_h_max]` meters:

```python
k = target_h / height                # also fixes the cm-vs-m unit mismatch (k ≈ 0.01×)
rim_dist = rim_edge / max(abs(cos a), abs(sin a))   # distance to the SQUARE rim along ray a
r_trunk = rim_dist + c.tree_gap
```

That `rim_dist` line is the "trees hug the square rim" math: for a ray at angle *a*, the
square's edge is not at constant radius like a circle — divide by the larger axis component.
Finally the translate subtracts the bbox center offset (some trees aren't centered on their
origin) and lifts the base to z=0.

### 3.3 `launch_scene.py` — the GUI entry point

Thin: parse args → load config → boot `SimulationApp(headless=...)` → either **open** an
existing `.usd` (`--usd out/iter_044.usd`, the reliable path) or **build** from a config —
and if it builds, immediately export + reopen (the Hydra sync trick, §2.5) so all trees render.
Then the `while sim_app.is_running(): sim_app.update()` loop hands control to you.
Gotcha that bit us: running it with **no arguments** uses `SceneConfig()` *defaults*, not the
latest iteration — always pass `--usd` or `--config`.

### 3.4 `render_scene.py` — headless one-shot renderer

The automation workhorse: config or `--usd` in, one PNG out. Study order: the fixed-exposure
carb settings block (§2.5) → build-or-open + the export/reopen sync → the Replicator rig →
`--preload` app-update loop (lets referenced assets/textures stream in before capture) →
`--cam-pos/--cam-look/--cam-focal` overrides (how all the diagnostic closeups/orbits were
shot; note `--cam-pos=-3,-2,1` needs the `=` form or argparse eats the minus sign).

### 3.5 `render_views.py` — the 5-angle evidence pass

Opens a saved stage and renders five fixed viewpoints (hero / low-near / top-down / close /
opposite-high) in one boot — building all render products first, then one warmup, then reading
each annotator. Exists because single-angle review kept hiding defects (floating decals only
visible at grazing angles, flicker only when dollying). `AUTOMATION.md` made it mandatory per
iteration, alongside a git commit per iteration.

### 3.6 The one-off diagnostic scripts (skim, but know why they exist)

`inspect_positions.py` (world bboxes of every placed thing — how "the tree is in the concrete"
and "cracks are 4 m wide" were *proven*), `inspect_trees.py` (native units/sizes — found the
cm-vs-m bug), `discover_trees.py` / `discover.py` (crawled the asset server for tree/material
URLs), `inspect_asset.py`, `probe_trees.py`, `probe_dirt_trees.py` (bindings, shader IDs, dirt
MDL search). Pattern to copy into your own practice: **when confused, write a tiny script that
prints the truth** instead of guessing from renders.

### 3.7 Data folders

`configs/` — one JSON per iteration = the project's *reproducible history* (diff two to see
exactly what changed). `out/` — built stages; `iter_042/043/044.usd` are also committed.
`finals/final_02/` — the current 8-shot beauty package. `assets/textures/` — **generated** maps:
`gravel_nrm/rough` (procedural FFT noise → normal/roughness), `patio_noise` (grey mottle,
mean 0.90), `concrete_noise` (blotches for barrier/pillar), `crack_diff/opacity` +
`spot_diff/opacity` (decal pairs; legacy now that cracks are geometry).

---

## Part 4 — War stories (the "what was hard?" answers)

Each one: symptom → root cause → fix → transferable lesson. These are in the git log; own them.

**#1 Everything imported was red.** Blender/Poly-Haven assets use UsdPreviewSurface, which RTX
renders as flat red. Fix: `convert_to_omnipbr` — trace each material's node graph to its real
texture files, rebuild as OmniPBR, rebind. Then leaves were *still* red: bindings live on
per-face **GeomSubsets**, not just meshes — the converter had to walk both. *Lesson: know your
renderer's material language; know USD binds materials per-face.*

**#2 A tree spawned in the middle of the concrete / a 2.7-km tree.** Two separate bugs:
`fir_sapling_medium` is a 3-tree *cluster* ~15 m wide (collapse to one), and NVIDIA vegetation
is authored in **centimeters** — referencing into a meters stage gave a 2699 m pine. Fix:
measure every tree's bbox and scale to a target height band — unit-agnostic by design.
*Lesson: never trust an asset's frame/units; measure with BBoxCache.*

**#3 Only the nearest tree rendered.** Headless builds showed one lush tree, the rest missing —
but the exported file had all ten. Live-referencing heavy assets didn't sync them into Hydra
(the render index). Fix: always export the stage and reopen it before rendering. *Lesson: when
data and picture disagree, decide which is truth (inspect the data!) and find the pipeline gap.*

**#4 Colors wouldn't match the references.** Auto-exposure re-brightened every render, so
material tweaks were invisible (patio measured 229/255 regardless). Fix: disable histogram
auto-exposure, fixed film ISO, ACES tonemap; then color-pick *rendered* pixels and tune albedo
against targets sampled from `ex_imgs`. *Lesson: control your measurement pipeline before
tuning; sRGB pixel ≠ material albedo.*

**#5 The great decal saga (cracks).** Sequence of failures: (a) opacity read the RGBA's dark
RGB as the mask → invisible (need a separate grayscale mask); (b) hand-built quads' UVs
sampled as one texel → invisible (use Kit's Plane, whose `st` RTX honors); (c) triplanar
projection made the crack **change orientation as the camera moved** (mesh UVs pin it);
(d) 8 mm of lift made every crack cast a shadow-twin ("cracks in pairs") — `doNotCastShadows`
+ 1–2 mm; (e) on the *pillar*, cutout decals near an analytic cylinder misrendered, a curved
hand mesh wouldn't sample opacity at all, narrow texture slices went blocky, a baked cylinder
texture wouldn't show. Final architecture: **opaque geometry ribbons** — floor cracks trace the
PNG's extracted centerline/width; the pillar crack's vertices lie on the cylinder surface.
*Lesson: when a rendering feature fights you five times, stop and change representation —
geometry is unambiguous where transparency is renderer-dependent.*

**#6 "It flickers when I zoom."** Two distinct causes over time: z-fighting (coplanar decal vs
patio — depth precision varies with camera distance) and triplanar re-projection. Diagnosis
method worth remembering: a **pure dolly test** — render the same target from 3 distances along
one ray; anything that changes is view-dependent and therefore a bug. *Lesson: build controlled
experiments; one variable at a time.*

**#7 The near-black pillar.** Baking `albedo = noise × 0.19` into a PNG rendered almost black:
PNGs are sRGB, tints are linear — baking needs `lin = srgb²·²(...)` math and a `^(1/2.2)`
re-encode. *Lesson: color pipelines have two spaces; know which one every number lives in.*

**#8 "4 parallel cracks" that weren't cracks.** The dark *stain* decals (an earlier feature
request) visually merged with the cracks. Fix: `n_spots=0`, plus min-separation and
single-component extraction so real cracks are countable and distinct. *Lesson: features
interact; review the scene as a user, not as a diff.*

---

## Part 5 — Mini-glossary

**Stage** USD scene document. **Prim** node in the stage. **Xform** transform-group prim.
**xformOp** one transform in a prim's ordered list. **Reference** inclusion of another USD file.
**defaultPrim** the entry prim of a file. **Hydra** USD's render-index layer feeding the
renderer. **RTX Real-Time** the ray-traced renderer mode used here. **MDL** NVIDIA material
language. **OmniPBR** the general MDL shader we parameterize. **UsdPreviewSurface** portable
USD shader (red in RTX). **GeomSubset** per-face material group. **primvars:st** mesh UVs.
**Triplanar / project_uvw** UV-less axis projection of textures. **Albedo** base color before
lighting. **Normal map** image faking bump lighting. **Cutout opacity** binary transparency by
mask + threshold. **DomeLight / DistantLight** sky / sun. **CollisionAPI / RigidBodyAPI**
static collider / dynamic body schemas. **Convex hull** simplified collision shell.
**Replicator** synthetic-data toolkit (cameras → numpy). **Annotator** a data channel (rgb,
depth…). **Subframes** accumulation samples per capture. **BBoxCache** world-bounds calculator.
**Rejection sampling** draw-until-valid placement. **Seeded RNG** reproducible randomness.
**Domain randomization** varying scene parameters across variants for robust learning.
**sRGB/linear** gamma-encoded storage vs light-linear math.

---

## Part 6 — Self-test (do this without the code open)

Whiteboard tier — you should nail all of these:
1. Walk the pipeline from `configs/iter_044.json` to `finals/final_02/final02_1_hero.png`,
   naming which file does each step.
2. Why must `SimulationApp` exist before `pxr` imports? Why do the scripts parse args first?
3. Why does the same seed always give the same scene? What silently breaks seed-stability?
4. Tell the red-assets story: cause, fix, and the GeomSubset twist.
5. Why are the cracks geometry rather than textures? Give at least three distinct decal
   failure modes that forced the change.
6. Why did cracks appear "in pairs," and what two changes fixed it?
7. Why is the pillar a mesh cylinder instead of `UsdGeom.Cylinder`?
8. What does the export/reopen trick fix, and what told us the bug was in rendering (not data)?
9. Why fixed exposure for the automation loop?
10. How does a tree end up exactly 6–8 m tall regardless of the asset's units?

Modify tier — do these hands-on, no AI help:
11. Add a 3rd guaranteed floor crack. (One config field.)
12. Make barriers randomize their scale ±20% per instance. (One function.)
13. Add a `puddle` decal: soft dark ellipse, `threshold=0.0`. (Clone the spot pathway.)
14. Move the sun to late-afternoon (low angle, warmer) via config only.
15. Write `generate_batch.py`: loop seeds 0–9, build each, export
    `out/env_00X.usd` + a `metadata.json` of the configs. (This is also roadmap item #1
    toward the dataset/paper.)

If you can do 1–10 aloud and 11–15 in an editor, you understand this project at the level that
matters — Tier 1 on the ideas, Tier 2 on the mechanics — and every claim in your README will
be one you can defend.
