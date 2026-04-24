from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a zeler-platform bootstrap job")
    parser.add_argument("--seller-id", required=True)
    parser.add_argument("--job-id", required=True)
    parser.parse_args()


if __name__ == "__main__":
    main()
