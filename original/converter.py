import re
import struct
from datetime import datetime
from pathlib import Path
from typing import List, TextIO

import click

tstamp_in_filename_pat = re.compile(r"(\d+)\.txt$")


@click.command()
@click.argument("input", type=click.File("r"))
@click.option(
    "-t",
    "--target",
    default="HP_3457A Dumps",
    show_default=True,
    help="Choose directory to save in",
)
def cli(input: TextIO, target: str) -> None:
    click.echo(f"Reading {input.name}...")
    date_in_filename = tstamp_in_filename_pat.search(str(input.name))
    if date_in_filename:
        stamp = datetime.fromtimestamp(float(date_in_filename[1]))
        stamp_str = stamp.strftime("%Y-%m-%d_%H-%M-%S")
        click.echo(
            f"Found timestamp {date_in_filename[1]}, converted to" f" {stamp_str}..."
        )
    else:
        stamp_str = ""

    _PEEK_PACK_F = struct.Struct("<h").pack

    target_dir = Path.home() / target
    target_dir.mkdir(parents=True, exist_ok=True)

    filename = f"HP_3457A_{stamp_str}"

    with open(target_dir / (filename + ".bin"), "wb") as f_bin:
        with open(target_dir / (filename + ".txt"), "w") as f_txt:

            start = -1
            dump: List[int] = []
            for line in input.readlines():
                ptr_str, val_str = line.split(": ")
                ptr = int(ptr_str)
                if start < 0:
                    start = ptr
                if ptr % 2 != 0:  # skip odd lines
                    continue
                val = int(float(val_str))
                ptr_incr_val, ptr_val = _PEEK_PACK_F(val)
                dump.append(ptr_val)
                dump.append(ptr_incr_val)

            pack_func = struct.Struct("B").pack
            for idx, b in enumerate(dump, start=start):
                f_bin.write(pack_func(b))
                f_txt.write(f"0x{idx:04X}: {b:02X}\n")


if __name__ == "__main__":
    cli()
