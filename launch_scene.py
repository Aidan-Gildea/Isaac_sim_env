#!/usr/bin/env python3
"""Interactive Isaac Sim sandbox for the infrastructure-inspection plaza (GUI).

Builds the scene via scene_lib.SceneBuilder (the single source of truth, shared with the headless
render_scene.py), then opens the GUI so you can mess around with materials and lighting.

Run inside the env_isaaclab conda env (use python -u for live logs):
    python -u launch_scene.py --config configs/iter_018.json   # GUI, current best look
    python -u launch_scene.py --usd out/iter_018.usd           # GUI, open a saved stage
    python -u launch_scene.py --seed 7                         # different random layout
    python -u launch_scene.py --headless --save out/sandbox.usd
"""
import argparse
import os

from scene_config import SceneConfig

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--config", type=str, default=None, help="SceneConfig JSON (default: built-in defaults)")
parser.add_argument("--usd", type=str, default=None, help="open this existing .usd instead of building")
parser.add_argument("--seed", type=int, default=None, help="override config seed")
parser.add_argument("--n-trees", type=int, default=None, help="override number of trees")
parser.add_argument("--headless", action="store_true", help="run without the GUI")
parser.add_argument("--save", type=str, default=None, help="export the authored stage to this .usd path")
args = parser.parse_args()

cfg = SceneConfig.load(args.config) if args.config else SceneConfig()
if args.seed is not None:
    cfg.seed = args.seed
if args.n_trees is not None:
    cfg.n_trees = args.n_trees

from isaacsim import SimulationApp  # noqa: E402

sim_app = SimulationApp({"headless": args.headless})

import omni.usd  # noqa: E402
from scene_lib import SceneBuilder  # noqa: E402

if args.usd:
    usd_path = args.usd if os.path.isabs(args.usd) else os.path.join(PROJECT_DIR, args.usd)
    omni.usd.get_context().open_stage(usd_path)
    print(f"[scene] opened {usd_path}", flush=True)
else:
    stage = omni.usd.get_context().get_stage()
    print("[scene] building...", flush=True)
    try:
        SceneBuilder(stage, cfg).build()
    except Exception:
        import traceback
        print("[scene][ERROR] build failed:")
        traceback.print_exc()

    # Building the heavy tree references live leaves most un-synced to Hydra (only the nearest renders).
    # Export + reopen forces a clean sync so ALL trees show in the GUI too.
    out = (args.save if os.path.isabs(args.save) else os.path.join(PROJECT_DIR, args.save)) \
        if args.save else os.path.join(PROJECT_DIR, "out", "_gui_tmp.usd")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    omni.usd.get_context().get_stage().GetRootLayer().Export(out)
    omni.usd.get_context().open_stage(out)
    print(f"[scene] exported + reopened ({out}) so all trees render", flush=True)

print("=" * 60, flush=True)
print("[scene] READY. Press Play for physics; edit materials/lights in the panels.", flush=True)
print("=" * 60, flush=True)

if args.headless:
    for _ in range(10):
        sim_app.update()
else:
    while sim_app.is_running():
        sim_app.update()
sim_app.close()
