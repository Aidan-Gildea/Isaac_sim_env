#!/usr/bin/env python3
"""SceneConfig: every tunable knob for the inspection-plaza scene, in one serializable place.

The automation loop edits a JSON copy of this config (one per iteration), re-renders, and compares
the screenshot to ex_imgs/. Nothing here imports Isaac Sim, so it is safe to load anywhere.
"""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from typing import List


@dataclass
class SceneConfig:
    # --- randomness ---
    seed: int = 0

    # --- ground / layout (meters) ---
    floor_half: float = 30.0
    patio_half: float = 7.0
    patio_top: float = 0.10        # patio top above floor (floor top = z 0)
    rim_top: float = 0.22          # rim (curb) top height
    rim_bar: float = 0.25          # rim bar half-thickness

    # --- surface materials (grey on 0=white..1=black reflectance; tile = triplanar repeat) ---
    floor_grey: float = 0.78
    floor_tile: float = 12.0
    floor_rough: float = 0.85
    floor_dirt: bool = True        # surround = real Omniverse Dirt material (else grey concrete)
    dirt_path: bool = True         # square dirt path around the patio, under the trees
    path_inset: float = 0.3        # path inner edge, this far outside the curb
    path_width: float = 3.0        # how far past the tree trunks the path extends
    path_tile: float = 8.0         # dirt texture tiling on the path
    patio_grey: float = 0.61
    patio_tile: float = 8.0
    patio_rough: float = 0.95
    patio_gravel: bool = True      # gravelly-asphalt normal/roughness on the patio (colour unchanged)
    rim_grey: float = 0.55         # darker curb; <=0 -> use library MDL instead of flat grey

    # --- patio scored-tile grid (the painted grid seams seen in ex_imgs) ---
    patio_grid: bool = True
    patio_grid_tiles: int = 5      # tiles across each axis -> (tiles-1) interior seam lines
    patio_grid_grey: float = 0.32  # seam colour (darker than the patio)
    patio_grid_w: float = 0.025    # half-width of a seam line

    # --- obstacles ---
    cone_half: float = 3.2         # half-side of the cone-bounds square
    cone_jitter: float = 0.7       # per-cone random offset -> vaguely (not exactly) square
    n_barriers: int = 3
    barrier_ring_r: float = 1.7
    barrier_scale: float = 0.8
    barrier_grey: float = 0.62     # >0 -> plain grey concrete (the asset's own texture is brick-like);
    #                                0 -> keep the asset's converted texture
    barrier_tile: float = 3.0      # finer tile -> more visible surface texture
    pillar_radius: float = 0.22
    pillar_height: float = 1.6
    pillar_grey: float = 0.50
    pillar_tile: float = 2.5

    # --- spall decals ---
    n_spalls: int = 2
    spall_half_min: float = 0.7
    spall_half_max: float = 1.2
    n_spots: int = 6               # a few big random dark stains on the pavement
    # cracks (single crack PNG): floor gets `crack_floor_base` always + 1 more with prob; column 50%
    crack_floor_base: int = 2
    crack_floor_extra_prob: float = 0.5
    crack_pillar_prob: float = 0.5
    crack_len_min: float = 3.0     # long-axis length on the patio (meters)
    crack_len_max: float = 5.0
    crack_tint: float = 0.5        # darken the crack decal so it reads
    crack_min_sep: float = 2.5     # min distance between floor cracks (not adjacent)

    # --- trees ---
    n_trees: int = 10
    tree_gap: float = 1.2          # trunk distance beyond the square rim edge
    tree_h_min: float = 5.0        # every tree normalized into this height band (meters)
    tree_h_max: float = 8.5
    # which NVIDIA SimReady trees are eligible (names under /NVIDIA/Assets/Vegetation/Trees)
    isaac_trees: List[str] = field(default_factory=lambda: [
        "Douglas_Fir", "White_Pine", "Yellow_Pine", "Red_Maple", "Sugar_Maple",
        "Japanese_Maple", "Red_Oak", "Scarlet_Oak", "Gray_Birch", "Black_Oak",
        "Orange_Tree", "Shumard_Oak", "Elm_Sapling",
    ])
    use_local_trees: bool = True   # also include the local Blender trees in the pool

    # --- boundary line ---
    line_color: List[float] = field(default_factory=lambda: [1.0, 0.78, 0.0])

    # --- lighting ---
    dome_color: List[float] = field(default_factory=lambda: [0.62, 0.66, 0.78])
    dome_intensity: float = 1000.0
    sun_color: List[float] = field(default_factory=lambda: [1.0, 0.89, 0.70])
    sun_intensity: float = 3200.0
    sun_angle: float = 0.53        # angular diameter (soft shadows)
    sun_rot: List[float] = field(default_factory=lambda: [-48.0, 0.0, 35.0])  # XYZ euler deg

    # --- capture camera (matches the ex_imgs elevated corner view) ---
    cam_pos: List[float] = field(default_factory=lambda: [17.0, -17.0, 12.0])
    cam_look: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.6])
    cam_focal: float = 18.0        # mm (lower = wider)
    res_w: int = 1024
    res_h: int = 576

    # ----- (de)serialization -----
    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def from_dict(cls, d: dict) -> "SceneConfig":
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})

    @classmethod
    def load(cls, path: str) -> "SceneConfig":
        with open(path) as f:
            return cls.from_dict(json.load(f))


if __name__ == "__main__":
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(os.path.join(here, "configs"), exist_ok=True)
    out = os.path.join(here, "configs", "base.json")
    SceneConfig().save(out)
    print(f"wrote default config -> {out}")
