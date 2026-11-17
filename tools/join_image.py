#!/usr/bin/env python3
"""Verify release parts and assemble the sparse image without overwriting a file."""
import argparse
from pathlib import Path
from release_tools import join


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        result = join(args.manifest, args.output)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, str(error) + '\n')
    print('Verified and assembled ' + str(result))


if __name__ == '__main__':
    main()

