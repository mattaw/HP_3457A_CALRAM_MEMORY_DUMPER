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
from .hp_3457A import HP_3457A, WriteProt

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
        logger_pyvisa.setLevel(debug_pyvisa.upper())
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

    console.print(
        f"[bold]ID {resource_idx} {resource_name}[/bold] Detected HP 3457A REV"
        f" [bold]{'.'.join(str(r) for r in hp.rev)}[/bold] with Main Controller Version"
        f" [bold]{hp.a1.BOARD_STR}[/bold]",
        highlight=False,
    )

    # Choose memory chip to dump
    sel_mem_table = Table()
    sel_mem_table.add_column("Reference", justify="right")
    sel_mem_table.add_column("Memory Chip")
    sel_mem_table.add_column("Address")
    sel_mem_table.add_column("Size")
    sel_mem_table.add_column("Protected", justify="center")

    for key, region in hp.a1.REGIONS.items():
        sel_mem_table.add_row(
            key,
            region.desc,
            f"0x{region.start:04x}",
            f"0x{region.size:04x}",
            "Yes" if isinstance(region, WriteProt) else "",
        )
    console.print(sel_mem_table)
    region = Prompt.ask(
        "Choose the memory region to dump: ",
        choices=[id for id in hp.a1.REGIONS.keys()],
    )

    # Dump to binary file and ASCII file
    console.print("")
    console.print(f"Dumping {region}...")
    target_dir = Path.home() / target
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = (
        f"HP_3457A_R{hp.rev[0]}-{hp.rev[1]}_A1_{hp.a1.BOARD_STR}"
        f"_{region}_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
    )
    with open(target_dir / (filename + ".bin"), "wb") as f_bin:
        with open(target_dir / (filename + ".txt"), "w") as f_txt:
            region = hp.a1.REGIONS[region]
            if not region.end:
                raise Exception("Need to implement single byte read/write")
            dump = hp.dump(start=region.start, end=region.end, progress=track)
            pack_func = struct.Struct("B").pack
            for idx, b in enumerate(dump, start=region.start):
                f_bin.write(pack_func(b))
                f_txt.write(f"0x{idx:04X}: {b:02X}\n")
