"""Check complete graph membership and sensitive-hit accounting, not global energy conservation."""

import argparse
from pathlib import Path

import numpy as np


def check(path):
    import truthinfo

    config = truthinfo.BuildConfig(postprocessing={"dropHitlessSimSubgraphs": False,
                                                   "collapseIntermediateGenParticles": False})
    result = truthinfo.build_from_file(path, config)
    graph = result.graph
    if not result.raw.is_consistent() or not graph.is_consistent():
        raise ValueError(f"Inconsistent truth graph in {path}")
    hits = result.event["Hits"]
    for channel in truthinfo.HitChannel:
        expected = float(hits["energy"][hits["channel"] == channel].sum())
        actual = sum(hit.energy for particle in graph.particles()
                     for hit in result.hit_index.direct_hits(int(channel), particle.id))
        if not np.isclose(actual, expected, rtol=1e-5, atol=1e-7):
            raise ValueError(f"{path}: {channel.name} energy mismatch: input={expected}, graph={actual}")
    particles = graph.particles()
    for table, node in (("GenParticles", "gen_node"), ("SimTracks", "sim_node")):
        expected = set(map(int, result.event[table]["id"]))
        actual = {int(result.raw.node(getattr(p, node))["key"])
                  for p in particles if getattr(p, node) >= 0}
        if actual != expected:
            raise ValueError(f"{path}: {table} membership changed during graph construction")
    counts = {"generator_only": sum(p.gen_node >= 0 and p.sim_node < 0 for p in particles),
              "generator_and_simulation": sum(p.gen_node >= 0 and p.sim_node >= 0 for p in particles),
              "simulation_only": sum(p.gen_node < 0 and p.sim_node >= 0 for p in particles)}
    print(f"{path.name}: {graph.n_particles} particles, {graph.n_vertices} vertices, "
          f"{len(hits['track_id'])} contributions; {counts}; complete membership and hit accounting OK")
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    paths = sorted(args.directory.glob("truth_event_*.root"))
    if not paths:
        parser.error("no truth_event_*.root files found")
    for path in paths:
        check(path)
