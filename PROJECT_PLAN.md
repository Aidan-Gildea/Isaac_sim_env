# Project Plan: Domain-Randomized Infrastructure Inspection Environment Generator

## Context

This folder (`/home/sun/Desktop/isaacsim_projects/isaac_sim_env`) is dedicated to a single
purpose: programmatically generating **10–15 high-fidelity, physics-enabled `.usd`
environments** for imitation learning, matching the outdoor "infrastructure inspection plaza"
in `ex_imgs/` (paved/asphalt plaza with a curb, concrete jersey barriers, a stone cylindrical
pillar, traffic cones, a yellow boundary outline, surrounding trees, and spall-damaged
asphalt). Each environment is a distinct domain-randomized variant (lighting, sky, greenery,
asphalt material + spalls, and obstacle/curb/boundary layout). A robot URDF (Ranger Mini,
already on disk) is **imported separately at train time**, so the environment `.usd` files
contain no robot.

**Chosen approach (confirmed):** offline parameterized builder → a fixed set of standalone
`.usd` files; robot kept separate; full randomization including obstacle layout.

**Scope & layering (confirmed):** this project is the **authoring layer only** — the `.usd`
builder. The `.usd` are authored **training-ready** (clean, stable prim paths + correct physics
schemas per object class) so that a later, *separate* milestone can add a thin `InteractiveSceneCfg`
which references a generated `.usd`, wraps the robot as an `Articulation`, and (optionally) adds
`EventManager` runtime DR. Because the target is **imitation learning** (demonstration-driven),
heavy env-cloning and runtime `EventManager` DR are optional — the 10–15 authored variants can
serve directly as demonstration/training scenes.

### Environment (verified)
- **Conda env `env_isaaclab`** (`/home/sun/miniforge3/envs/env_isaaclab`, Python 3.11.15) is the
  target runtime. Isaac Sim is the **pip-installed `isaacsim` 5.1.0.0** packages in this env
  (namespace is `isaacsim.*`, not `omni.isaac.*`); `isaacsim-replicator` 5.1.0.0 is present.
- IsaacLab is pip-installed (editable) from `/home/sun/IsaacLab/source/*` (`isaaclab` 0.54.2)
  into the same env. **Run scripts with `conda activate env_isaaclab` then `python <script>.py`**
  — not `./isaaclab.sh -p` and not `/home/sun/isaac-sim/python.sh`.
- Assets present: 47 spall textures (2476×2475 PNG) in `Spalls/`; Ranger Mini meshes in `~/Downloads/meshes`.
- User will collect the real prims (barriers, pillar, asphalt+curb, cones, trees) in Isaac Sim and drop them into `assets/`.

### Toolchain decision
Build on **IsaacLab `sim_utils` spawners** (the pattern referenced in
`~/IsaacLab/scripts/tutorials/00_sim/spawn_prims.py`) for spawning, physics, and materials —
`UsdFileCfg`, `RigidBodyPropertiesCfg`, `CollisionPropertiesCfg`, `MassPropertiesCfg`,
`DomeLightCfg`, `DistantLightCfg`, `GroundPlaneCfg`, `PreviewSurfaceCfg` (see `isaaclab.sim`).
Use raw `pxr` USD APIs (`UsdGeom`, `UsdPhysics`, `PhysxSchema`, `Gf`, `Sdf`) for low-level
authoring (decals, boundary lines, scatter) and `omni.usd.get_context().save_as_stage(path)`
to snapshot each variant. Randomization is done by **direct, seeded authoring** (numpy RNG)
so sampled values are baked into the saved stage deterministically — not via Replicator's
per-frame graph (which is oriented to SDG capture and had flagged light-intensity quirks).
Run headless via IsaacLab's `AppLauncher` (`--headless`) using the `env_isaaclab` conda Python.

## Project structure

```
isaac_sim_env/
├── CLAUDE.md                  # research policy (exists)
├── ex_imgs/  Spalls/          # reference imgs (3) + spall textures (47) (exist)
├── assets/                    # user-collected prims (USD), scanned at build time
│   ├── barriers/ pillar/ cones/ trees/ ground/   # ground = asphalt + curb prims
├── config/
│   └── randomization.py       # RandomizationCfg + asset-path constants (dataclasses)
├── src/
│   ├── asset_registry.py      # scan assets/<category>/*.usd; synthetic fallbacks
│   ├── scene_builder.py       # assemble one plaza scene from a sampled config
│   ├── randomizer.py          # seed -> sampled params (lighting, poses, textures, scatter)
│   ├── materials.py           # asphalt OmniPBR/MDL + spall decal application
│   ├── physics.py             # rigid body + convex-decomp collision helpers
│   └── export.py              # save_as_stage + per-variant metadata
├── build_env.py               # entrypoint: build ONE variant (--seed, --out)
├── generate_batch.py          # loop N seeds in one app session -> 10–15 .usd + metadata.json
├── out/                       # generated env_000.usd … env_014.usd
└── README.md                  # how to run + how to drop in collected prims
```

## Module responsibilities & key APIs to reuse

- **`asset_registry.py`** — Scan `assets/<category>/` for `.usd`/`.usda`. Expose per-category
  lists to the randomizer. If a category is empty, return a **synthetic-primitive fallback**
  (e.g. a `CuboidCfg` jersey-barrier proxy, `CylinderCfg` pillar, `ConeCfg` cone) so the whole
  pipeline is runnable/verifiable *before* the real prims are collected, then drop-in upgrades
  when assets arrive. No code change needed when assets are added.

- **`randomizer.py`** — One `seed -> SampledScene` function using `numpy.random.default_rng(seed)`.
  Samples: dome-light HDRI + intensity + yaw, sun (distant light) elevation/azimuth/intensity/
  color-temp, asphalt base material variant, number+placement+texture+scale+opacity of spall
  decals, obstacle counts/poses/yaw within the plaza, curb/boundary inset, tree species/count/
  ring-placement/scale/rotation. Returns a plain dataclass (fully serializable for metadata).

- **`scene_builder.py`** — Given a `SampledScene`, author `/World`:
  1. Physics scene + gravity (`UsdPhysics.Scene`, GPU dynamics); static ground collider.
  2. Asphalt plaza slab + raised pad; curb border; synthetic **yellow boundary** strips at
     sampled inset (thin colored/emissive quads via `UsdGeom`).
  3. Obstacles: reference asset USDs (`UsdFileCfg`/`add_reference_to_stage`) at sampled poses —
     barriers + pillar as static colliders (kinematic), cones as knock-over rigid bodies (per `physics.py`).
  4. Trees scattered in a ring outside the plaza (reference tree USDs; sampled species/scale/rot).
  5. Lights: `DomeLightCfg` (sky/HDRI) + `DistantLightCfg` (sun).
  Mirror the `spawn_prims.py` `cfg.func(prim_path, cfg, translation=...)` idiom.

- **`materials.py`** — Asphalt = OmniPBR/MDL with noisy base color/normal/roughness; **spalls
  applied as projected decal quads** (random spall PNG from the 47, random pos/scale/rot/opacity)
  on the asphalt — matches "spalls are textures applied onto the asphalt." Verify exact OmniPBR
  import path against the installed 5.1 build.

- **`physics.py`** — Per-class physics treatment (geometry and physics are decoupled in USD):
  - Ground / curb / plaza pad → **collider-only** static (`CollisionAPI`, no rigid body).
  - Barriers + pillar → **collider-only** static, placed kinematically at sampled poses; apply
    **convex decomposition** (`PhysxSchema.PhysxConvexDecompositionCollisionAPI`) for the mesh
    collider (5.1 mesh import doesn't always set collision approximation automatically).
  - Cones → **dynamic** (`RigidBodyAPI` + `MassAPI` + convex-hull collision) so the robot can
    knock them over; sample mass + friction.
  - Trees → **no colliders** (visual-only decoration outside the boundary), near-zero physics cost.

- **`export.py`** — `omni.usd.get_context().save_as_stage(out/env_XXX.usd)`; append the full
  `SampledScene` dict to `out/metadata.json` (seed → all sampled params) for reproducibility.

- **`build_env.py` / `generate_batch.py`** — IsaacLab `AppLauncher` boilerplate
  (`parser`, `AppLauncher.add_app_launcher_args`, `--headless`). Batch driver loops seeds in a
  **single app session**, calling `omni.usd.get_context().new_stage()` per variant, then build →
  brief sim step to settle cones only → save. Determinism: variant N always uses `base_seed + N`.

## Randomization spec (full, incl. layout)
- **Lighting/sky:** HDRI choice, dome intensity, dome yaw; sun elevation/azimuth/intensity/temp.
- **Asphalt:** base material variant + N spall decals (texture/pose/scale/opacity) + optional cracks.
- **Greenery:** tree species, count, ring placement, scale, rotation.
- **Layout:** obstacle counts + poses + yaw authored kinematically (barriers/pillar fixed; cones
  briefly settled), curb dimensions, boundary inset.

## Implementation notes / risks (per CLAUDE.md, verify before relying on these)
- Confirm exact 5.1 signatures against the installed build/docs during implementation:
  OmniPBR/MDL material import path, dome-light HDRI/intensity attribute names, convex-decomp API,
  and whether to import collected prims via `sim_utils.UsdFileCfg` vs `add_reference_to_stage`.
- 5.1 dome-light intensity via Replicator was flagged buggy — we author intensity directly on the
  USD light prim, sidestepping that path.
- Keep the synthetic-fallback path working so the pipeline is testable before real prims exist.

## Verification (end-to-end)
1. **Smoke (no real assets):** `conda activate env_isaaclab && python generate_batch.py --num 2 --headless` → produces
   `out/env_000.usd`, `out/env_001.usd` + `metadata.json` using synthetic fallbacks. Confirm files
   open without errors.
2. **Determinism:** same seed → identical `metadata.json` entry and prim layout.
3. **GUI/physics:** open a variant in Isaac Sim, press Play → barriers/pillar stay put, cones are
   knock-over, nothing interpenetrates the ground, collisions valid; visually photoreal.
4. **With real prims:** drop collected USDs into `assets/`, regenerate 10–15, compare against
   `ex_imgs/` for fidelity; spot-check that spalls, trees, lighting, and layout actually vary.
5. **Robot sanity (later):** reference the Ranger Mini URDF/USD into one variant and confirm it
   spawns and collides with the environment.

## Build order (milestones)
1. Scaffolding + `AppLauncher` boilerplate + `asset_registry` with synthetic fallbacks.
2. `scene_builder` ground/curb/boundary + lights (static, single seed) → save one `.usd`.
3. Physics per object class (static colliders for barriers/pillar; knock-over rigid-body cones) + brief cone settle.
4. `materials` asphalt + spall decals; tree scatter.
5. `randomizer` wiring of all axes + `generate_batch` for 10–15 variants + metadata.
6. Verify in GUI; swap in real collected prims; tune ranges to match `ex_imgs/`.
