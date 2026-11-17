#!/usr/bin/env python3
"""Prepare verified local GitHub Release parts; does not upload or flash anything."""
import argparse
from pathlib import Path
from release_tools import prepare


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--notes', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare(args.candidate, args.checkpoint, args.output, args.notes)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, str(error) + '\n')
    print(f"Prepared {result['version']}: {len(result['image']['parts'])} verified parts in {args.output}")


if __name__ == '__main__':
    main()

