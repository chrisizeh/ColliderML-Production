"""Copy existing truth events, retaining detector-hit contributors and ancestry."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "simulation"))
from truth.selection import detector_truth


def main():
    import truthinfo

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Directory containing truth_event_*.root")
    parser.add_argument("destination", type=Path, help="New output directory")
    args = parser.parse_args()
    paths = sorted(args.source.glob("truth_event_*.root"))
    if not paths:
        parser.error("no truth_event_*.root files found")
    args.destination.mkdir(parents=True, exist_ok=False)
    for path in paths:
        event = truthinfo.read_event(path)
        selected = detector_truth(event)
        truthinfo.write_event(args.destination / path.name, selected)
        print(f"{path.name}: {len(event['SimTracks']['id'])} -> "
              f"{len(selected['SimTracks']['id'])} simulation tracks; "
              f"all {len(event['Hits']['track_id'])} hit contributions preserved")


if __name__ == "__main__":
    main()
