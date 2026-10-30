"""Create a small, deterministic HepMC3 source for an actual DDSim smoke run."""

import argparse
from pathlib import Path


def write_input(destination):
    import pyhepmc

    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    with pyhepmc.open(destination, "w") as writer:
        for number in (41, 42):
            event = pyhepmc.GenEvent(pyhepmc.Units.GEV, pyhepmc.Units.MM)
            event.event_number = number
            collision = pyhepmc.GenVertex()
            collision.add_particle_in(pyhepmc.GenParticle((0., 0., 1., 1.), 11, 4))
            collision.add_particle_in(pyhepmc.GenParticle((0., 0., -1., 1.), -11, 4))
            resonance = pyhepmc.GenParticle((0., 0., 0., 2.), 25, 2)
            collision.add_particle_out(resonance)
            decay = pyhepmc.GenVertex()
            decay.add_particle_in(resonance)
            for sign in (-1, 1):
                decay.add_particle_out(pyhepmc.GenParticle((float(sign), 0., 0., 1.), sign * 11, 1))
            event.add_vertex(collision)
            event.add_vertex(decay)
            for item in (*event.particles, *event.vertices):
                item.attributes["colliderml_source"] = "signal"
                item.attributes["colliderml_bunch_crossing"] = 0
            writer.write(event)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    write_input(parser.parse_args().output)
