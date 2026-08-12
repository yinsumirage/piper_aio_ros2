"""Read-only replay preview. Hardware publication is intentionally absent in v0."""

import argparse

import h5py


def main(argv=None):
    parser = argparse.ArgumentParser(description="Preview a piper-aio HDF5 episode without publishing commands")
    parser.add_argument("episode", help="Path to an episode_*.hdf5 file")
    parser.add_argument("--mode", choices=("joint", "eef"), default="joint")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="reserved explicit execution gate; v0 refuses because publishing is not implemented",
    )
    args = parser.parse_args(argv)
    if args.execute:
        parser.error("v0 has no command publisher; --execute is intentionally refused and no command was sent")

    with h5py.File(args.episode, "r") as root:
        source = root["/action"] if args.mode == "joint" else root["/observations/eef_pose"]
        print(f"DRY RUN: {args.mode} replay would process {len(source)} frames of shape {source.shape[1:]}")
        print("No ROS publisher was created; no hardware command was sent.")


if __name__ == "__main__":
    main()
