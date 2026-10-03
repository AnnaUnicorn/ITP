"""Read-only package and hardware preflight for FLUX.2 Klein 4B."""

import importlib.metadata
import os
import subprocess
import sys


def main():
    for package in ("torch", "diffusers", "transformers", "accelerate", "fastapi"):
        print(f"{package}: {importlib.metadata.version(package)}")
    import torch
    from diffusers import Flux2KleinPipeline

    print(f"pipeline: {Flux2KleinPipeline.__name__}")
    print(f"cuda_available: {torch.cuda.is_available()}")
    for query in ("index,name,memory.total,memory.free,utilization.gpu",
                  "pid,process_name,used_gpu_memory"):
        kind = "compute-apps" if query.startswith("pid") else "gpu"
        result = subprocess.run(
            ["nvidia-smi", f"--query-{kind}={query}", "--format=csv,noheader"],
            capture_output=True, text=True, check=False,
        )
        print(f"nvidia-smi {kind}:\n{result.stdout.strip() or '(none)'}")
    for index in range(torch.cuda.device_count()):
        free, total = torch.cuda.mem_get_info(index)
        print(f"gpu[{index}]: {torch.cuda.get_device_name(index)}; free={free // 2**20} MiB; total={total // 2**20} MiB")
    gpu = int(os.environ.get("ITP_KLEIN_GPU", "0"))
    if not torch.cuda.is_available() or gpu >= torch.cuda.device_count():
        raise RuntimeError("Selected GPU is not available")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"preflight failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
