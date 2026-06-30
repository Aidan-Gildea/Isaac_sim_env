#!/usr/bin/env python3
"""Headless: build the plaza from a SceneConfig and render one fixed-camera frame to a PNG.

    python -u render_scene.py --config configs/base.json --out screenshots/iter_000.png

The camera pose lives in the config (cam_pos / cam_look / cam_focal), chosen to match the elevated
corner view of ex_imgs/. Used by the automation loop: render -> compare to ex_imgs -> edit config.
"""
import argparse
import os

from scene_config import SceneConfig

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

parser = argparse.ArgumentParser()
parser.add_argument("--config", type=str, default=None, help="SceneConfig JSON (default: built-in defaults)")
parser.add_argument("--usd", type=str, default=None, help="open this existing .usd instead of building")
parser.add_argument("--out", type=str, default="screenshots/render.png", help="output PNG path")
parser.add_argument("--seed", type=int, default=None, help="override config seed")
parser.add_argument("--subframes", type=int, default=24, help="RTX accumulation subframes (denoise quality)")
parser.add_argument("--steps", type=int, default=30, help="render steps (asset/texture streaming warmup)")
parser.add_argument("--preload", type=int, default=120, help="app update steps to fully stream assets before capture")
parser.add_argument("--save-usd", type=str, default=None, help="also export the authored stage here")
parser.add_argument("--cam-pos", type=str, default=None, help="override camera position 'x,y,z'")
parser.add_argument("--cam-look", type=str, default=None, help="override camera look-at 'x,y,z'")
parser.add_argument("--cam-focal", type=float, default=None, help="override camera focal length (mm)")
args = parser.parse_args()

cfg = SceneConfig.load(args.config) if args.config else SceneConfig()
if args.seed is not None:
    cfg.seed = args.seed
if args.cam_pos:
    cfg.cam_pos = [float(v) for v in args.cam_pos.split(",")]
if args.cam_look:
    cfg.cam_look = [float(v) for v in args.cam_look.split(",")]
if args.cam_focal is not None:
    cfg.cam_focal = args.cam_focal

from isaacsim import SimulationApp  # noqa: E402

sim_app = SimulationApp({"headless": True, "enable_cameras": True})

import carb  # noqa: E402
import numpy as np  # noqa: E402
import omni.usd  # noqa: E402
import omni.replicator.core as rep  # noqa: E402
from PIL import Image  # noqa: E402

from scene_lib import SceneBuilder  # noqa: E402

# FIXED exposure (auto-exposure makes albedo->pixel unpredictable and washes the patio out). With a
# fixed exposure the surface greys map deterministically, so we can colour-match the ex_imgs.
_settings = carb.settings.get_settings()
_settings.set_bool("/rtx/post/histogram/enabled", False)  # disable auto-exposure
_settings.set_int("/rtx/post/tonemap/op", 1)              # ACES filmic
_settings.set_float("/rtx/post/tonemap/filmIso", 100.0)   # fixed film speed (exposure)
_settings.set_bool("/rtx/post/dlss/enabled", False)

if args.usd:
    usd_path = args.usd if os.path.isabs(args.usd) else os.path.join(PROJECT_DIR, args.usd)
    omni.usd.get_context().open_stage(usd_path)
    stage = omni.usd.get_context().get_stage()
    print(f"[render] opened existing stage <- {usd_path}", flush=True)
else:
    stage = omni.usd.get_context().get_stage()
    print(f"[render] building scene (seed={cfg.seed})...", flush=True)
    SceneBuilder(stage, cfg).build()

    # Building the heavy referenced trees in a live session leaves most of them un-synced to Hydra
    # (only the nearest renders). Exporting and re-opening the stage forces a clean sync so ALL
    # trees render. So: always export, then reopen, before capturing.
    if args.save_usd:
        out_usd = args.save_usd if os.path.isabs(args.save_usd) else os.path.join(PROJECT_DIR, args.save_usd)
    else:
        out_usd = os.path.join(PROJECT_DIR, "out", "_render_tmp.usd")
    os.makedirs(os.path.dirname(out_usd), exist_ok=True)
    stage.GetRootLayer().Export(out_usd)
    print(f"[render] exported -> {out_usd}; reopening for a clean render sync...", flush=True)
    omni.usd.get_context().open_stage(out_usd)
    stage = omni.usd.get_context().get_stage()

# fixed capture camera (look-at handles orientation)
cam = rep.create.camera(position=tuple(cfg.cam_pos), look_at=tuple(cfg.cam_look),
                        focal_length=cfg.cam_focal)
rp = rep.create.render_product(cam, (cfg.res_w, cfg.res_h))
ann = rep.AnnotatorRegistry.get_annotator("rgb")
ann.attach([rp])

# Heavy vegetation streams in asynchronously; pump the app loop so ALL assets/materials finish
# loading before capture (otherwise only the nearest trees render).
print(f"[render] preloading assets ({args.preload} app updates)...", flush=True)
for _ in range(args.preload):
    sim_app.update()

print(f"[render] warming up ({args.steps} steps x {args.subframes} subframes)...", flush=True)
for _ in range(args.steps):
    rep.orchestrator.step(rt_subframes=args.subframes)

data = ann.get_data()
arr = np.asarray(data)
if arr.dtype != np.uint8:
    arr = (np.clip(arr, 0.0, 1.0) * 255).astype(np.uint8)
rgb = arr[..., :3]

out = args.out if os.path.isabs(args.out) else os.path.join(PROJECT_DIR, args.out)
os.makedirs(os.path.dirname(out), exist_ok=True)
Image.fromarray(rgb).save(out)
print(f"[render] wrote {rgb.shape[1]}x{rgb.shape[0]} -> {out}", flush=True)

sim_app.close()
