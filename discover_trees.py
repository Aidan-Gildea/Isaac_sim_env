#!/usr/bin/env python3
"""Headless: hunt the Isaac/Omniverse asset server for tree / vegetation USDs."""
from isaacsim import SimulationApp

app = SimulationApp({"headless": True})

import omni.client  # noqa: E402

try:
    from isaacsim.storage.native import get_assets_root_path
except Exception:
    from isaacsim.core.utils.nucleus import get_assets_root_path

ROOT = get_assets_root_path()
print("ASSET_ROOT =", ROOT, flush=True)


def listdir(url):
    res, entries = omni.client.list(url)
    if res != omni.client.Result.OK:
        return None
    return [e.relative_path for e in entries]


# breadth-first crawl, collecting anything that smells like a tree/plant
SEEDS = [
    "/NVIDIA/Assets/Vegetation",
    "/NVIDIA/Assets/ArchVis/Residential/Landscaping",
    "/NVIDIA/Assets/Skies",
    "/Isaac/Environments",
    "/Isaac/Props",
    "/NVIDIA/Assets",
]
KEYWORDS = ("tree", "plant", "shrub", "bush", "fir", "pine", "oak", "maple",
            "vegetation", "foliage", "palm", "birch", "sapling", "hedge", "fern")

hits = []
seen = set()
queue = [ROOT + s for s in SEEDS]
MAX_DEPTH_URLS = 4000
while queue and len(seen) < MAX_DEPTH_URLS:
    url = queue.pop(0)
    if url in seen:
        continue
    seen.add(url)
    entries = listdir(url)
    if entries is None:
        continue
    for name in entries:
        low = name.lower()
        child = url.rstrip("/") + "/" + name
        if low.endswith((".usd", ".usda", ".usdc", ".usdz")):
            if any(k in low for k in KEYWORDS):
                hits.append(child)
        elif "." not in name:  # subdir
            # only descend into promising subtrees to keep it bounded
            if any(k in low for k in KEYWORDS) or url.endswith(
                ("Vegetation", "Landscaping", "Environments", "Props", "Assets", "ArchVis", "Residential")
            ):
                queue.append(child)

print(f"\n### {len(hits)} tree-ish USDs found:")
for h in sorted(set(hits)):
    print("  ", h.replace(ROOT, "<ROOT>"), flush=True)

app.close()
