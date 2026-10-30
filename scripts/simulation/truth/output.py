"""Install live DDG4 capture and publish schema-validated single-event files."""

from pathlib import Path

import numpy as np

from .generator import generator_tables
from .selection import detector_truth


class TruthOutput:
    def __init__(self, input_path, output_directory, *, run_id, events, signal_only=False):
        import truthinfo

        if truthinfo.SCHEMA_VERSION != 2:
            raise RuntimeError("Live truth output requires standalone-truthinfo schema 2; use the matching checkout")
        if input_path is None:
            raise ValueError("Truth output requires explicit HepMC3 input; use particlegun_gen.py for gun events")
        if events <= 0 or run_id < 0:
            raise ValueError("Truth output requires a positive event count and a nonnegative run ID")
        self.input_path = Path(input_path)
        self.directory = Path(output_directory)
        self.capture = self.directory / ".truth_capture"
        self.run_id = run_id
        self.events = events
        self.signal_only = signal_only
        if (self.capture.exists() or any(self.directory.glob("truth_event_*.root")) or
                any(self.directory.glob("transport_event_*.root"))):
            raise FileExistsError("Truth output already exists; select a fresh output directory")
        self.capture.mkdir()

    def configure(self, ddsim):
        """Use DDSim's output hook to adopt a standard Geant4OutputAction."""
        import ROOT
        import DDG4

        if ddsim.numberOfThreads != 1:
            raise ValueError("Truth output currently requires threads=1")
        for prefix in Path("/spack/opt/spack/linux-x86_64").glob("geant4-*/include/Geant4"):
            ROOT.gInterpreter.AddIncludePath(str(prefix))
        source = Path(__file__).parent / "native" / "TruthCapture.cpp"
        if not ROOT.gInterpreter.Declare(source.read_text()):
            raise RuntimeError("Failed to compile DDG4 truth collector")
        # The hook replaces DDSim's default output setup, so install that output
        # explicitly before adopting the additional capture action.
        ddsim.outputConfig._configureEDM4HEP(ddsim, DDG4.Geant4(DDG4.Kernel()))
        action = DDG4.EventAction(DDG4.Kernel(), "ColliderMLTruthCapture/TruthCapture", True)
        action.Output = str(self.capture)
        action.HandleErrorsAsFatal = True
        DDG4.Kernel().eventAction().adopt(action)
        return action

    def finish(self):
        """Match captures by simulation ordinal, then atomically write final files."""
        import pyhepmc
        import truthinfo
        import uproot

        paths = sorted(self.capture.glob("capture_*.root"), key=lambda p: int(p.stem.split("_")[-1]))
        if len(paths) != self.events:
            raise RuntimeError(f"Expected {self.events} truth captures, found {len(paths)}")
        outputs = []
        with pyhepmc.open(self.input_path) as reader:
            generator = iter(reader)
            for ordinal, path in enumerate(paths):
                event = next(generator, None)
                if event is None:
                    raise ValueError("HepMC3 input ended before the captured simulation events")
                with uproot.open(path) as source:
                    header = source["Event"].arrays(library="np")
                    if int(header["simulation_id"][0]) != ordinal or int(header["source_id"][0]) != event.event_number:
                        raise ValueError("HepMC3 and simulation event identities disagree")
                    tables, input_ids, provenance = generator_tables(event, signal_only=self.signal_only)
                    imported = source["Inputs"].arrays(library="np")
                    gp = tables["GenParticles"]
                    if not (np.array_equal(imported["input_id"], np.arange(len(input_ids))) and
                            np.array_equal(imported["pdg_id"], gp["pdg_id"]) and
                            np.array_equal(imported["status"].astype(np.uint16).view(np.int16), gp["status"])):
                        raise ValueError("DDG4 reader identities do not match the original generator record")
                    tracks = source["Tracks"].arrays(library="np")
                    vertices = source["Vertices"].arrays(library="np")
                    tables.update(self._simulation_tables(tracks, vertices, input_ids, provenance))
                    tables["Hits"] = source["Hits"].arrays(library="np")
                tables["Event"] = {
                    "schema_version": [truthinfo.SCHEMA_VERSION], "run_id": [self.run_id],
                    "event_id": [event.event_number], "boundary_available": [False], "backscatter_available": [False],
                }
                tables["BoundaryCrossings"] = truthinfo.empty_table("BoundaryCrossings")
                destination = self.directory / f"truth_event_{event.event_number:06d}.root"
                truthinfo.write_event(destination, detector_truth(truthinfo.validate_event(tables)))
                path.unlink()
                outputs.append(destination)
        self.capture.rmdir()
        return outputs

    @staticmethod
    def _simulation_tables(tracks, vertices, input_ids, provenance):
        ids = tracks["id"]
        primary = tracks["input_id"] >= 0
        if np.any(tracks["input_id"][primary] >= len(input_ids)):
            raise ValueError("Unknown generator input association")
        gen_ids = np.full(len(ids), -1, dtype=np.int32)
        gen_ids[primary] = input_ids[tracks["input_id"][primary]]
        rows = {int(track): i for i, track in enumerate(ids)}
        interaction = {int(track): provenance[int(gen)] for track, gen in zip(ids[primary], gen_ids[primary])}
        for track in ids:
            current, path, visiting = int(track), [], set()
            while current not in interaction:
                if current in visiting or current not in rows:
                    raise ValueError("Transport ancestry is cyclic or unresolved")
                visiting.add(current)
                path.append(current)
                current = int(tracks["parent_id"][rows[current]])
            for child in path:
                interaction[child] = interaction[current]
        interactions = np.asarray([interaction[int(track)] for track in ids], dtype=np.uint32)
        vertex_interaction = {}
        vertex_parent = dict(zip(map(int, vertices["id"]), map(int, vertices["parent_track_id"])))
        for track, vertex, parent in zip(ids, tracks["production_vertex_id"], tracks["parent_id"]):
            vertex = int(vertex)
            if vertex not in vertex_parent or vertex_parent[vertex] != int(parent):
                raise ValueError("Track creation vertex disagrees with live transport parent")
            source = interaction[int(track)]
            if vertex in vertex_interaction and vertex_interaction[vertex] != source:
                raise ValueError("Creation step contains different interactions")
            vertex_interaction[vertex] = source
        if set(vertex_interaction) != set(vertex_parent):
            raise ValueError("Capture contains an unused creation vertex")
        return {
            "SimTracks": {"id": ids, "interaction_id": interactions, "pdg_id": tracks["pdg_id"],
                          "production_vertex_id": tracks["production_vertex_id"], "is_primary": primary,
                          "generator_particle_id": gen_ids,
                          "backscattered": np.zeros(len(ids), dtype=bool),
                          **{name: tracks[name] for name in ("px", "py", "pz", "energy")}},
            "SimVertices": {**vertices, "interaction_id": np.asarray(
                [vertex_interaction[int(vertex)] for vertex in vertices["id"]], dtype=np.uint32)},
        }
