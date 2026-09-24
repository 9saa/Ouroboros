"""Banner + module panel rendering."""

import shutil


BANNER = r"""
▄████▄ ▄▄ ▄▄ ▄▄▄▄   ▄▄▄  ▄▄▄▄   ▄▄▄  ▄▄▄▄   ▄▄▄   ▄▄▄▄   ██  ██  ▄██▄    ████▄   ████▄
██  ██ ██ ██ ██▄█▄ ██▀██ ██▄██ ██▀██ ██▄█▄ ██▀██ ███▄▄   ██▄▄██ ██  ██    ▄██▀    ▄▄██
▀████▀ ▀███▀ ██ ██ ▀███▀ ██▄█▀ ▀███▀ ██ ██ ▀███▀ ▄▄██▀    ▀██▀   ▀██▀  ▄ ███▄▄ ▄ ▄▄▄█▀
"""

def print_header(modules: list) -> None:
    lines = BANNER.splitlines()
    pad = max(len(l) for l in lines) if lines else 0

    right = ["MODULES"]
    for m in modules:
        right.append(f"  \u2022 {m.name}")
    right_width = max((len(r) for r in right), default=0)

    term_width = shutil.get_terminal_size((120, 30)).columns
    side_by_side = term_width >= pad + right_width + 6

    if side_by_side:
        total = max(len(lines), len(right))
        for i in range(total):
            left = lines[i] if i < len(lines) else " " * pad
            r = right[i] if i < len(right) else ""
            print(f"{left}  \u2502  {r}")
    else:
        for line in lines:
            print(line)
        print()
        print("MODULES")
        for m in modules:
            print(f"  \u2022 {m.name}")
