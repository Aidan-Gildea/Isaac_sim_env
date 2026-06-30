# Automated scene-matching loop

Goal: iteratively drive the generated plaza toward the three reference photos in `ex_imgs/`
(tile/floor colour, tree count/colour/size, layout, lighting) by a tight
**edit → render → compare → adjust** cycle.

## Pieces

| File | Role |
|---|---|
| `scene_config.py` | `SceneConfig` dataclass — every tunable knob + JSON load/save. No Isaac imports. |
| `scene_lib.py` | `SceneBuilder` — authors the scene onto a USD stage from a `SceneConfig`. |
| `render_scene.py` | **Headless**: build from a config JSON → render the fixed camera → write a PNG. |
| `launch_scene.py` | Interactive GUI over the same builder (for eyeballing / manual material tweaks). |
| `configs/` | One JSON per iteration (`base.json`, `iter_001.json`, …). |
| `screenshots/` | One rendered PNG per iteration (`iter_001.png`, …). |
| `ex_imgs/` | The three target reference images. |

The scene definition lives **only** in `scene_lib.py`; both the GUI and the headless renderer use
it, so there is no drift between what you tune and what gets captured.

## Per-iteration rules (MANDATORY)

- **Commit every single iteration to git.** After producing each `iter_NNN` (config + render),
  `git add -A && git commit` with a message describing the change. This gives a restore point for
  every step (e.g. the iter_037 baseline, tag `iter_037-baseline`). Never batch multiple iterations
  into one commit.
- **Render 5 angles, not just the hero.** For each iteration, after `--save-usd out/iter_NNN.usd`,
  run the multi-view shooter and scrutinize all five (different angles + closeness) for problems
  that a single shot hides (floating decals, z-fighting/flicker, projection flips, scale):
  ```bash
  python -u render_views.py --usd out/iter_NNN.usd --outdir finals/iter_NNN --tag iNNN
  ```
  Views: `1_hero`, `2_low_near`, `3_topdown`, `4_close`, `5_opp_high`.

## The loop

1. **Render** the current config to a screenshot:
   ```bash
   conda run -n env_isaaclab python -u render_scene.py \
       --config configs/iter_NNN.json --out screenshots/iter_NNN.png --save-usd out/iter_NNN.usd
   ```
   then the 5-angle pass (above), then **commit**.

2. **Compare** the 5 shots against the three `ex_imgs/` on:
   - patio tile colour + the grid/seam pattern
   - floor colour
   - number of trees, their colour, size, and how much they fill the frame
   - barrier / cone / boundary layout
   - overall lighting (brightness, warmth, shadow softness, sky tone)

3. **Adjust** — copy the config and edit fields, e.g.:
   ```python
   from scene_config import SceneConfig
   c = SceneConfig.load("configs/iter_NNN.json")
   c.patio_grey = 0.55          # darker tiles
   c.n_trees = 14               # denser ring
   c.dome_intensity = 1500      # brighter
   c.save("configs/iter_NNN+1.json")
   ```
   Three kinds of change are available:
   1. **material** — `*_grey`, `*_tile`, `*_rough`, `line_color`, lighting colours/intensities.
   2. **spacing / size** — `cone_half`, `barrier_ring_r`, `barrier_scale`, `pillar_radius`,
      `tree_gap`, `tree_h_min/max`, `patio_half`.
   3. **swap assets** — change `isaac_trees` (any names under
      `/NVIDIA/Assets/Vegetation/Trees`), toggle `use_local_trees`, change counts.

4. **Repeat** until the render is near-identical to `ex_imgs/`.

## Camera

The capture camera matches the elevated corner view of `ex_imgs` and is part of the config
(`cam_pos`, `cam_look`, `cam_focal`, `res_w/h`). Tune those to reframe; everything else stays put.

## Notes / known follow-ups

- The headless capture enables histogram **auto-exposure + ACES tonemapping** (in `render_scene.py`)
  so the RTX render matches the GUI viewport instead of blowing out to white.
- The cone "triangle mesh collision … falling back to convexHull" messages are harmless.
- Open gaps vs `ex_imgs` to chip away at in the loop: patio needs a **tiled grid** pattern;
  trees should fill the frame corners more (wider FOV or larger/closer ring); fine-tune greys.

## Discovery helpers (already written)

- `discover_trees.py` — lists tree/vegetation USDs on the Nucleus asset server.
- `inspect_trees.py` — native units + bbox size of each Isaac vegetation tree.
- `inspect_positions.py <usd>` — world-space bounds of the placed prims (verify no floating/overlap).
