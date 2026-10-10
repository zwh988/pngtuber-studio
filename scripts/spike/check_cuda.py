import sys

import torch


def main() -> None:
    print(f"python: {sys.version.split()[0]}")
    print(f"torch: {torch.__version__}")
    print(f"torch built for CUDA: {torch.version.cuda}")
    available = torch.cuda.is_available()
    print(f"cuda available: {available}")
    if available:
        props = torch.cuda.get_device_properties(0)
        print(f"gpu: {props.name}")
        print(f"total VRAM: {props.total_memory / 1024**3:.2f} GiB")
        free, total = torch.cuda.mem_get_info()
        print(f"free VRAM now: {free / 1024**3:.2f} GiB of {total / 1024**3:.2f} GiB")


if __name__ == "__main__":
    main()