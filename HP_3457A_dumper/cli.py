import logging
import struct
from datetime import datetime
from logging import basicConfig, getLogger
from pathlib import Path

import pyvisa
import rich_click as click
from rich.logging import RichHandler
from rich.progress import track
from rich.prompt import Prompt
from rich.table import Table

from .__about__ import __version__
from .console import console
from .hp_3457A import HP_3457A

LOG_LEVELS = {
    "DEBUG",
    "INFO",
    "WARNING",
    "ERROR",
    "CRITICAL",
}  # sadly getLevelNamesMapping is CPython >=3.11

basicConfig(
    format="%(module)-20s %(message)s",
    level=logging.WARNING,
    handlers=[RichHandler(rich_tracebacks=True)],
)
logger = getLogger(__name__)


@click.command()
@click.option(
    "-d",
    "--debug",
    default="warning",
    show_default=True,
    help="Choose logging: critical, error, warning, info, debug",
)
@click.option(
    "--debug-pyvisa",
    default="warning",
    show_default=True,
    help="Choose PyVISA logging: critical, error, warning, info, debug",
)
@click.option(
    "-t",
    "--target",
    default="HP_3457A Dumps",
    show_default=True,
    help="Choose directory to save in",
)
def cli(debug: str, debug_pyvisa: str, target: str) -> None:
    # Logging
    if debug.upper() in LOG_LEVELS:
        loggers = [
            logging.getLogger(name)
            for name in logging.root.manager.loggerDict
            if name != "pyvisa"
        ]
        for log in loggers:
            log.setLevel(debug.upper())
    else:
        console.print(
            f"Debug level of '{debug}' invalid. Valid levels are:"
            f" {', '.join(LOG_LEVELS)}"
        )
        exit(-1)
    if debug_pyvisa.upper() in LOG_LEVELS:
        logger_pyvisa = getLogger("pyvisa")
        logger_pyvisa.setLevel(logging.INFO)
    else:
        console.print(
            f"PyVISA debug level of '{debug_pyvisa}' invalid. Valid levels are:"
            f" {', '.join(LOG_LEVELS)}"
        )
        exit(-1)

    # Choose GPIB INSTR to interrogate
    console.rule(f"HP 3457A CalRAM Memory Dumper Version {__version__}", align="left")
    rm = pyvisa.ResourceManager()
    unfiltered_resources = rm.list_resources()
    resources = [
        res for res in unfiltered_resources if HP_3457A.PYVISA_GPIB_PATTERN.match(res)
    ]
    resources.sort()
    if not resources:
        console.print(
            "[red]No suitable PyVISA resources found. Please see PyVISA and VISA"
            " documentation to continue."
        )
    resources_idxs = range(len(resources))
    console.print("PyVISA Detected Instruments:")
    sel_hp_table = Table()
    sel_hp_table.add_column("ID", justify="right")
    sel_hp_table.add_column("VISA Resource Name")
    for idx, res in zip(resources_idxs, resources):
        sel_hp_table.add_row(f"{idx}", res)
    console.print(sel_hp_table)
    resource_idx = Prompt.ask(
        "Choose ID of HP 3457A: ", choices=[f"{idx}" for idx in resources_idxs]
    )
    resource_name = resources[int(resource_idx)]

    # Detect HP 3457A if it is one
    try:
        hp = HP_3457A.select(resource_name=resource_name)
    except pyvisa.errors.VisaIOError:
        console.print(
            f"[bold]ID {resource_idx} - {resource_name}:[/bold] Timeout - Exiting."
        )
        exit(-1)
    if hp.a1 == HP_3457A.A1_03457_66501:
        a1_str = "03457_66501"
    elif hp.a1 == HP_3457A.A1_03457_66511:
        a1_str = "03457_66511"
    else:
        raise Exception("Should not have been possible: Unknown A1 board detected.")
    console.print(
        f"[bold]ID {resource_idx} {resource_name}[/bold] Detected HP 3457A REV"
        f" [bold]{'.'.join(str(r) for r in hp.rev)}[/bold] with Main Controller Version"
        f" [bold]{a1_str}[/bold]",
        highlight=False,
    )

    # Choose memory chip to dump
    sel_mem_table = Table()
    sel_mem_table.add_column("ID", justify="right")
    sel_mem_table.add_column("Memory Chip")
    sel_mem_table.add_column("Address")
    sel_mem_table.add_column("Size")
    sel_mem_table.add_column("Prot. Addr.")
    sel_mem_table.add_column("Prot. Size")

    for key, chip in hp.memory_map.items():
        sel_mem_table.add_row(
            key,
            chip.desc,
            f"0x{chip.read_[0]:04x}",
            f"0x{chip.read_[1]:04x}",
            f"0x{chip.protr[0]:04x}" if chip.protr else "-",
            f"0x{chip.protr[1]:04x}" if chip.protr else "-",
        )
    console.print(sel_mem_table)
    memory_chip = Prompt.ask(
        "Choose the memory chip to dump: ", choices=[id for id in hp.memory_map.keys()]
    )

    # Dump to binary file and ASCII file
    console.print("")
    console.print(f"Dumping {memory_chip}...")
    target_dir = Path.home() / target
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = (
        "HP_3457A_A1_"
        f"{'03457-66501' if hp.a1 == HP_3457A.A1_03457_66501 else '03457-66511'}"
        f"_{memory_chip}_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
    )
    with open(target_dir / (filename + ".bin"), "wb") as f_bin:
        with open(target_dir / (filename + ".txt"), "w") as f_txt:
            memory_chip_map = hp.memory_map[memory_chip]
            if memory_chip_map.protr is None:
                start_ptr = memory_chip_map.read_[0]
                size = memory_chip_map.read_[1]
            else:
                start_ptr = min(memory_chip_map.read_[0], memory_chip_map.protr[0])
                size = memory_chip_map.read_[1] + memory_chip_map.protr[1]
            dump = hp.dump(start=start_ptr, size=size, progress=track)
            pack_func = struct.Struct("B").pack
            for idx, b in enumerate(dump, start=start_ptr):
                f_bin.write(pack_func(b))
                f_txt.write(f"0x{idx:04X}: {b:02X}\n")
