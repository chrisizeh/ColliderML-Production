"""Retain detector-hit contributors and their original ancestry."""

import numpy as np


def detector_truth(event):
    """Select hit-connected SIM/GEN branches without reparenting or changing hits.

    The input must be a schema-validated event. A particle is relevant if it
    owns a recorded sensitive-detector hit or is an ancestor of such a particle.
    Passive-material interactions alone do not qualify. The retained graph is
    intentionally incomplete for exclusive decay/energy-balance studies.
    """
    tables = dict(event.tables)

    def select(name, mask):
        tables[name] = {key: values[mask] for key, values in event[name].items()}

    tracks, vertices = event["SimTracks"], event["SimVertices"]
    vertex_parent = dict(zip(map(int, vertices["id"]), map(int, vertices["parent_track_id"])))
    parents = {int(track): vertex_parent[int(vertex)]
               for track, vertex in zip(tracks["id"], tracks["production_vertex_id"])}
    kept = set()
    for track in map(int, event["Hits"]["track_id"]):
        while track != -1 and track not in kept:
            kept.add(track)
            track = parents[track]
    select("SimTracks", np.isin(tracks["id"], list(kept)))
    select("SimVertices", np.isin(vertices["id"], tables["SimTracks"]["production_vertex_id"]))
    select("BoundaryCrossings", np.isin(event["BoundaryCrossings"]["track_id"], list(kept)))

    # Follow all incoming generator parents (including multi-parent vertices),
    # but never include a hitless sibling merely because its parent is kept.
    incoming, outgoing = event["GenVertexIncoming"], event["GenVertexOutgoing"]
    production = dict(zip(map(int, outgoing["particle_id"]), map(int, outgoing["vertex_id"])))
    gen_parents = {}
    for vertex, particle in zip(incoming["vertex_id"], incoming["particle_id"]):
        gen_parents.setdefault(int(vertex), []).append(int(particle))
    pending = [int(p) for p in tables["SimTracks"]["generator_particle_id"] if p != -1]
    gen_kept, gen_vertices = set(), set()
    while pending:
        particle = pending.pop()
        if particle in gen_kept:
            continue
        gen_kept.add(particle)
        if particle in production:
            vertex = production[particle]
            gen_vertices.add(vertex)
            pending.extend(gen_parents.get(vertex, []))
    select("GenParticles", np.isin(event["GenParticles"]["id"], list(gen_kept)))
    select("GenVertices", np.isin(event["GenVertices"]["id"], list(gen_vertices)))
    for name in ("GenVertexIncoming", "GenVertexOutgoing"):
        select(name, np.isin(event[name]["vertex_id"], list(gen_vertices)) &
               np.isin(event[name]["particle_id"], list(gen_kept)))
    # Preserve collision identities, including the required signal row when an
    # event has no hits. Hits and their original ownership remain byte-for-byte.
    return tables
