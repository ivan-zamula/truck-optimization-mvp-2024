"""Calculate synthetic truck assignments for a volume target."""

import argparse
from dataclasses import asdict
import json
from .model import Scenario, Simulation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=float, default=120, help="Target volume in cubic meters")
    parser.add_argument("--duration", type=float, default=1800, help="Available simulation time in seconds")
    parser.add_argument("--policy", choices=["earliest_delivery", "round_robin"], default="earliest_delivery")
    parser.add_argument("--events", action="store_true")
    args = parser.parse_args()
    try:
        scenario = Scenario(target_m3=args.target, time_limit_seconds=args.duration, policy=args.policy)
    except ValueError as exc:
        parser.error(str(exc))
    simulation = Simulation(scenario)
    result = asdict(simulation.run())
    if args.events:
        result["assignments"] = [asdict(a) for a in simulation.assignments]
        result["events"] = [asdict(e) for e in simulation.events]
        result["motion"] = [asdict(m) for m in simulation.motion]
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
