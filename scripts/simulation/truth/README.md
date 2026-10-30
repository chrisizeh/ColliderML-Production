# Detector-hit truth capture

`truth_events` saves only particles that own a recorded sensitive-detector hit
and their original SIM/GEN ancestors. A particle that interacts only with passive
material is discarded unless its descendants contribute hits. Every recorded
tracker/calorimeter contribution is preserved, including zero-energy hit records.
No hit is reassigned to a different ancestor, and no momentum or physics cut is
introduced. Hitless sibling branches and unrelated generator branches are removed.
The resulting graph is not a complete decay record for energy-balance studies.

The collector temporarily holds creation ancestry in memory until detector hits
are known. Only hit-connected tracks and vertices are written to its temporary
capture. The schema-validated `truth_event_<id>.root` is the final output; the
temporary capture is then deleted. Full steps, tracking endpoints and transport
audit files are not produced. There is no full-transport mode.

DDG4's configured `keepAllParticles` value is respected. The independent collector
uses original Geant4 hit ownership, so reduced EDM truth does not reparent the
standalone event graph. All momentum/energy values use GeV, positions mm, times ns.
Capture requires one worker and explicit HepMC input with collision provenance
(or an explicit signal-only declaration for legacy PU0 input).

Checks in the physics-container environment with `truthinfo` available:

```bash
python tests/simulation/test_truth_output.py -v
python tests/simulation/test_truth_selection.py -v
python scripts/cli/check_truth_events.py /path/to/runs/0
```

To reduce existing standalone truth files without rerunning simulation, with
`truthinfo` and uproot available:

```bash
python scripts/cli/reduce_truth_events.py /path/to/old/runs/0 /path/to/new/runs/0
```

The destination must be new; source data is never overwritten.
