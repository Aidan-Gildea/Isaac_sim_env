#!/usr/bin/env python3
"""Headless: open a saved .usd and render it from 5 fixed viewpoints (different angles + closeness)
into an output folder. Used by the iterative refinement loop so each iteration can be scrutinized
from multiple angles, not just the hero shot.

    python -u render_views.py --usd out/iter_037.usd --outdir finals/iter_037 --tag i037
"""
import argparse
import os

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

parser = argparse.ArgumentParser()
parser.add_argument("--usd", type=str, required=True, help="existing .usd to render")
parser.add_argument("--outdir", type=str, required=True, help="folder for the 5 PNGs")
parser.add_argument("--tag", type=str, default="view", help="filename prefix")
parser.add_argument("--preload", type=int, default=120, help="app updates to stream assets")
parser.add_argument("--subframes", type=int, default=24)
parser.add_argument("--steps", type=int, default=24)
args = parser.parse_args()

# 5 viewpoints: (name, camera_pos, look_at, focal_mm) -- different angles AND closeness levels
VIEWS = [
    ("1_hero",      (17.0, -17.0, 27.0), (0.0, 0.0, 1.0), 24.0),   # elevated overview
    ("2_low_near",  (11.0,   8.0,  5.0), (0.0, 0.0, 1.0), 28.0),   # low eye-level, opposite corner
    ("3_topdown",   ( 0.0,   0.0, 42.0), (0.0, 0.0, 0.0), 35.0),   # straight down (layout)
    ("4_close",     ( 5.5,  -7.0,  4.5), (0.0, 0.0, 0.4), 30.0),   # close on the patio/cracks
    ("5_opp_high",  (-16.0, -13.0, 22.0),(0.0, 0.0, 1.0), 26.0),   # opposite high corner
]

from isaacsim import SimulationApp  # noqa: E402

sim_app = SimulationApp({"headless": True, "enable_cameras": True})

import carb  # noqa: E402
import numpy as np  # noqa: E402
import omni.usd  # noqa: E402
import omni.replicator.core as rep  # noqa: E402
from PIL import Image  # noqa: E402

# fixed exposure (match render_scene.py) so brightness is comparable across views/iterations
_s = carb.settings.get_settings()
_s.set_bool("/rtx/post/histogram/enabled", False)
_s.set_int("/rtx/post/tonemap/op", 1)
_s.set_float("/rtx/post/tonemap/filmIso", 100.0)
_s.set_bool("/rtx/post/dlss/enabled", False)

usd_path = args.usd if os.path.isabs(args.usd) else os.path.join(PROJECT_DIR, args.usd)
omni.usd.get_context().open_stage(usd_path)
print(f"[views] opened {usd_path}", flush=True)

outdir = args.outdir if os.path.isabs(args.outdir) else os.path.join(PROJECT_DIR, args.outdir)
os.makedirs(outdir, exist_ok=True)

# build all render products up front, then stream/warm up once
products = []
for name, pos, look, focal in VIEWS:
    cam = rep.create.camera(position=tuple(pos), look_at=tuple(look), focal_length=focal)
    rp = rep.create.render_product(cam, (1024, 576))
    ann = rep.AnnotatorRegistry.get_annotator("rgb")
    ann.attach([rp])
    products.append((name, ann))

print(f"[views] preloading ({args.preload})...", flush=True)
for _ in range(args.preload):
    sim_app.update()
for _ in range(args.steps):
    rep.orchestrator.step(rt_subframes=args.subframes)

for name, ann in products:
    arr = np.asarray(ann.get_data())
    if arr.dtype != np.uint8:
        arr = (np.clip(arr, 0, 1) * 255).astype(np.uint8)
    out = os.path.join(outdir, f"{args.tag}_{name}.png")
    Image.fromarray(arr[..., :3]).save(out)
    print(f"[views] wrote {out}", flush=True)

sim_app.close()
