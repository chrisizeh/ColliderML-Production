"""Detector selection must preserve hits, ownership and complete parent chains."""

from pathlib import Path
import sys
import unittest

import numpy as np
import truthinfo

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "simulation"))
from truth.selection import detector_truth


def event_with_hits():
    tables = {name: truthinfo.empty_table(name) for name in truthinfo.SCHEMA}

    def table(name, **values):
        size = len(next(iter(values.values())))
        tables[name] = {key: np.asarray(values.get(key, np.zeros(size)), dtype=dtype)
                        for key, dtype in truthinfo.SCHEMA[name].items()}

    table("Event", schema_version=[2], run_id=[0], event_id=[41])
    table("Interactions", interaction_id=[0], is_signal=[True])
    # Two incoming generator parents, one useful child, one hitless sibling.
    table("GenParticles", id=[1, 2, 3, 4], pdg_id=[11, -11, 22, 12])
    table("GenVertices", id=[-1])
    table("GenVertexIncoming", vertex_id=[-1, -1], particle_id=[1, 2])
    table("GenVertexOutgoing", vertex_id=[-1, -1], particle_id=[3, 4])
    # 10 -> 20 -> 30 reaches the detector, 40 is its hitless sibling, and
    # 50 is an unrelated injected particle. IDs need not be contiguous/sorted.
    table("SimTracks", id=[30, 10, 50, 20, 40], pdg_id=[11, 22, 12, 22, 22],
          production_vertex_id=[300, 100, 500, 200, 200],
          is_primary=[False, True, True, False, False],
          generator_particle_id=[-1, 3, 4, -1, -1])
    table("SimVertices", id=[100, 200, 300, 500], parent_track_id=[-1, 10, 20, -1])
    table("Hits", track_id=[30, 30], channel=[0, 2], energy=[0., 1.25],
          cell_id=[2**63 + 7, 12], collection_id=[0, 1])
    return truthinfo.validate_event(tables)


class TestDetectorTruth(unittest.TestCase):
    def test_keeps_hits_and_ancestry_but_drops_hitless_siblings(self):
        original = event_with_hits()
        selected = truthinfo.validate_event(detector_truth(original))
        np.testing.assert_array_equal(selected["SimTracks"]["id"], [30, 10, 20])
        np.testing.assert_array_equal(selected["SimVertices"]["id"], [100, 200, 300])
        np.testing.assert_array_equal(selected["GenParticles"]["id"], [1, 2, 3])
        for key in original["Hits"]:
            np.testing.assert_array_equal(original["Hits"][key], selected["Hits"][key])
        for name, columns in selected.tables.items():
            repeated = detector_truth(selected)[name]
            for key, values in columns.items():
                np.testing.assert_array_equal(values, repeated[key])
        self.assertEqual(len(original["SimTracks"]["id"]), 5)

    def test_no_hits_retains_only_event_and_collision_identity(self):
        tables = dict(event_with_hits().tables)
        tables["Hits"] = truthinfo.empty_table("Hits")
        selected = truthinfo.validate_event(detector_truth(truthinfo.validate_event(tables)))
        for name in ("SimTracks", "SimVertices", "GenParticles", "GenVertices",
                     "GenVertexIncoming", "GenVertexOutgoing", "BoundaryCrossings", "Hits"):
            self.assertEqual(len(next(iter(selected[name].values()))), 0, name)
        self.assertEqual(selected.event_id, 41)
        self.assertEqual(len(selected["Interactions"]["interaction_id"]), 1)


if __name__ == "__main__":
    unittest.main()
