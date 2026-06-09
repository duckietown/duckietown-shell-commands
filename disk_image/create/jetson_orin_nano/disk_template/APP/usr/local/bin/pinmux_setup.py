#!/usr/bin/python3
import os
import subprocess
import sys

BIT10 = 1 << 10  # GPIO select
BIT4  = 1 << 4
BIT6  = 1 << 6

# GPIO pins and respective pinmux registers and directions
PINMUX = {
    "P29": (0x2430068, "out"),  # HAT reset
    "P31": (0x2430070, "out"),  # Motor
    "P33": (0x2434040, "out"),  # Motor
    "P37": (0x243D048, "out"),  # Button LED
    # "PXX": (0x........, "in"),
}

def sh(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, text=True).strip()

def rd(reg: int) -> int:
    out = sh(["busybox", "devmem", f"0x{reg:X}"])
    return int(out, 16)

def wr(reg: int, val: int) -> None:
    sh(["busybox", "devmem", f"0x{reg:X}", "w", f"0x{val:08X}"])

def set_gpio_mode(old: int, direction: str) -> int:
    # Always force GPIO select bit to 0
    base = old & ~BIT10
    if direction == "out":
        return base & ~(BIT4 | BIT6)
    if direction == "in":
        return base | (BIT4 | BIT6)
    raise ValueError(f"Unknown direction: {direction}")

def main() -> int:
    if os.geteuid() != 0:
        print("Run as root: sudo python3 pinmux_set.py", file=sys.stderr)
        return 1

    if not os.path.exists("/etc/nv_tegra_release"):
        print("Not a Jetson rootfs (/etc/nv_tegra_release missing). Refusing.", file=sys.stderr)
        return 2

    # Ensure busybox is present
    try:
        sh(["busybox", "--help"])
    except Exception:
        print("busybox missing. Install with: sudo apt-get install -y busybox", file=sys.stderr)
        return 3

    for name, (reg, direction) in PINMUX.items():
        old = rd(reg)
        new = set_gpio_mode(old, direction)
        wr(reg, new)
        verify = rd(reg)

        print(f"{name} {direction.upper():>3} reg=0x{reg:X}: 0x{old:08X} -> 0x{new:08X} (readback 0x{verify:08X})")

        if verify != new:
            print(f"WARNING: readback mismatch for {name}", file=sys.stderr)

    return 0

if __name__ == "__main__":
    raise SystemExit(main())