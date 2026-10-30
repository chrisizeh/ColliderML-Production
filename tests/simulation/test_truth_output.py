"""Small provenance and retained-ancestry checks; DDSim is exercised separately."""

from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
import pyhepmc

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "simulation"))
from truth.generator import generator_tables, tag_source
from truth.output import TruthOutput
from truth.smoke_input import write_input


class TestTruthOutput(unittest.TestCase):
    def test_generator_provenance_and_explicit_signal_only_input(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.hepmc3"
            write_input(source)
            with pyhepmc.open(source) as reader:
                event = next(iter(reader))
            tables, ids, provenance = generator_tables(event)
            self.assertEqual(event.event_number, 41)
            self.assertEqual(len(ids), 5)
            self.assertEqual(set(provenance.values()), {0})
            self.assertEqual(tables["GenParticles"]["pdg_id"], [11, -11, 25, -11, 11])
            for particle in event.particles:
                del particle.attributes["colliderml_source"]
            with self.assertRaisesRegex(ValueError, "Missing interaction provenance"):
                generator_tables(event)
            self.assertEqual(generator_tables(event, signal_only=True)[0]["Interactions"]["interaction_id"], [0])

    def test_pileup_tags_are_persistent_and_not_inferred_from_coordinates(self):
        with tempfile.TemporaryDirectory() as directory:
            source, tagged = (Path(directory) / name for name in ("input.hepmc3", "pileup.hepmc3"))
            write_input(source)
            tag_source(source, tagged, signal=False)
            with pyhepmc.open(tagged) as reader:
                events = list(reader)
            labels = [{str(p.attributes["colliderml_source"]) for p in event.particles} for event in events]
            self.assertEqual(labels, [{"pileup:0"}, {"pileup:1"}])
            with self.assertRaisesRegex(ValueError, "signal collision"):
                generator_tables(events[0])

    def test_live_siblings_share_a_vertex_and_keep_four_momentum(self):
        tracks = {"id": np.array([4, 8, 9, 10], dtype=np.int32),
                  "input_id": np.array([1, -1, -1, -1], dtype=np.int32),
                  "pdg_id": np.array([22, 11, 22, -11], dtype=np.int32),
                  "parent_id": np.array([-1, 4, 8, 4], dtype=np.int32),
                  "production_vertex_id": np.array([1, 25, 30, 25], dtype=np.int32)}
        tracks.update({name: np.arange(4, dtype=float) for name in ("px", "py", "pz", "energy")})
        vertices = {"id": np.array([1, 25, 30]), "parent_track_id": np.array([-1, 4, 8]),
                    "process_subtype": np.array([0, 14, 3], dtype=np.uint16),
                    **{name: np.zeros(3) for name in ("x", "y", "z", "time")}}
        tables = TruthOutput._simulation_tables(tracks, vertices, np.array([10, 20]), {10: 0, 20: 7})
        np.testing.assert_array_equal(tables["SimTracks"]["interaction_id"], [7, 7, 7, 7])
        np.testing.assert_array_equal(tables["SimTracks"]["generator_particle_id"], [20, -1, -1, -1])
        np.testing.assert_array_equal(tables["SimTracks"]["production_vertex_id"], [1, 25, 30, 25])
        self.assertEqual(len(tables["SimVertices"]["id"]), 3)
        for key in ("px", "py", "pz", "energy"):
            np.testing.assert_array_equal(tables["SimTracks"][key], tracks[key])
        # Keep both the GEN association and real parent of a prescribed decay daughter.
        tracks["input_id"][1] = 0
        tables = TruthOutput._simulation_tables(tracks, vertices, np.array([10, 20]), {10: 7, 20: 7})
        self.assertTrue(tables["SimTracks"]["is_primary"][1])
        self.assertEqual(tables["SimVertices"]["parent_track_id"][1], 4)
        tracks["parent_id"][2] = 9
        with self.assertRaisesRegex(ValueError, "cyclic or unresolved"):
            TruthOutput._simulation_tables(tracks, vertices, np.array([10, 20]), {10: 7, 20: 7})


if __name__ == "__main__":
    unittest.main()
