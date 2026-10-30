"""Generator topology and provenance, preserved before transport overwrites it."""

from pathlib import Path

import numpy as np

SOURCE_ATTRIBUTE = "colliderml_source"
CROSSING_ATTRIBUTE = "colliderml_bunch_crossing"


def tag_source(source, destination, *, signal):
    """Label each physical collision before ACTS merges its particles/vertices."""
    import pyhepmc

    with pyhepmc.open(source) as reader, pyhepmc.open(destination, "w") as writer:
        for index, event in enumerate(reader):
            label = "signal" if signal else f"pileup:{index}"
            for item in (*event.particles, *event.vertices):
                item.attributes[SOURCE_ATTRIBUTE] = label
                item.attributes[CROSSING_ATTRIBUTE] = 0
            writer.write(event)
    return Path(destination)


def generator_tables(event, *, signal_only=False):
    """Flatten one HepMC3 event and return DDG4 reader-index associations.

    DDG4's HEPMC3EventReader assigns input IDs by particle iteration order. The
    capture adapter verifies that exact order, PDG and status against Inputs;
    no phase-space matching or topology-based collision inference is used.
    """
    import pyhepmc

    event.set_units(pyhepmc.Units.GEV, pyhepmc.Units.MM)
    particles = list(event.particles)
    labels = {}
    particle_sources = {}
    for particle in particles:
        if SOURCE_ATTRIBUTE not in particle.attributes:
            if not signal_only:
                raise ValueError("Missing interaction provenance; regenerate with truth_events or declare truth_signal_only")
            label, crossing = "signal", 0
        else:
            label = str(particle.attributes[SOURCE_ATTRIBUTE])
            crossing = int(str(particle.attributes[CROSSING_ATTRIBUTE]))
        previous = labels.setdefault(label, crossing)
        if previous != crossing:
            raise ValueError("A generator interaction has inconsistent bunch crossings")
        particle_sources[particle.id] = label
    if labels.get("signal") != 0:
        raise ValueError("Generator event must contain the signal collision at bunch crossing zero")
    if signal_only and set(labels) != {"signal"}:
        raise ValueError("truth_signal_only cannot be used with pileup-labelled input")
    ordered = ["signal", *sorted(label for label in labels if label != "signal")]
    interaction_ids = {label: i for i, label in enumerate(ordered)}
    provenance = {p.id: interaction_ids[particle_sources[p.id]] for p in particles}
    tables = {
        "Interactions": {"interaction_id": list(range(len(ordered))),
                         "bunch_crossing": [labels[label] for label in ordered],
                         "is_signal": [label == "signal" for label in ordered]},
        "GenParticles": {
            "id": [p.id for p in particles],
            "interaction_id": [provenance[p.id] for p in particles],
            "pdg_id": [p.pid for p in particles], "status": [p.status for p in particles],
            **{axis: [getattr(p.momentum, axis) for p in particles] for axis in ("px", "py", "pz")},
            "energy": [p.momentum.e for p in particles],
        },
        "GenVertices": {name: [] for name in ("id", "interaction_id", "x", "y", "z", "time")},
        "GenVertexIncoming": {"vertex_id": [], "particle_id": []},
        "GenVertexOutgoing": {"vertex_id": [], "particle_id": []},
    }
    for vertex in event.vertices:
        members = [*vertex.particles_in, *vertex.particles_out]
        sources = {provenance[p.id] for p in members}
        if len(sources) != 1:
            raise ValueError("Generator vertex must belong to exactly one interaction")
        values = (vertex.id, sources.pop(), vertex.position.x, vertex.position.y,
                  vertex.position.z, vertex.position.t / 299.792458)
        for name, value in zip(tables["GenVertices"], values):
            tables["GenVertices"][name].append(value)
        for name, members in (("GenVertexIncoming", vertex.particles_in),
                              ("GenVertexOutgoing", vertex.particles_out)):
            tables[name]["vertex_id"].extend([vertex.id] * len(members))
            tables[name]["particle_id"].extend(p.id for p in members)
    return tables, np.asarray([p.id for p in particles], dtype=np.int32), provenance
