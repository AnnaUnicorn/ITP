"""Download the small, pinned foreground model; never download during application startup."""

import argparse
import hashlib
from pathlib import Path
from urllib.request import urlopen

SOURCE = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx"
EXPECTED_MD5 = "8e83ca70e441ab06c318d82300c84806"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=SOURCE, help="Official source or an operator-owned mirror")
    parser.add_argument("--output", type=Path, default=Path("models/u2netp.onnx"))
    args = parser.parse_args()
    if args.output.exists():
        data = args.output.read_bytes()
        if hashlib.md5(data).hexdigest() != EXPECTED_MD5:
            raise SystemExit("Existing file has a different checksum; refusing to overwrite it")
    else:
        with urlopen(args.url, timeout=60) as response:
            data = response.read(8 * 1024 * 1024 + 1)
        if len(data) > 8 * 1024 * 1024 or hashlib.md5(data).hexdigest() != EXPECTED_MD5:
            raise SystemExit("Downloaded model failed size/checksum validation")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation preserves an existing file even if another installer races us.
        with args.output.open("xb") as handle:
            handle.write(data)
    print(f"Verified: {args.output.resolve()}")
    print(f"Bytes: {len(data)}")
    print(f"SHA256: {hashlib.sha256(data).hexdigest()}")


if __name__ == "__main__":
    main()
