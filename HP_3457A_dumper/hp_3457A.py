# HP 3457A Arbitrary Memory Dumper
# Andrei Aldea 2018
# Asks for Beginning and End Adress in Decimal to Read
# Reads twice, does MD5 checksum of the two files created and tells user if they match

from __future__ import annotations

import hashlib
import re
import struct
from functools import total_ordering
from logging import getLogger
from typing import (
    Callable,
    ClassVar,
    Dict,
    Iterable,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
    Type,
)

import pyvisa
from attr import define, field, frozen
from pyvisa.resources import GPIBInstrument

logger = getLogger(__name__)


@total_ordering
@frozen(eq=False)
class MemRegion:
    desc: str = field()
    start: int = field()  # Start ADDR
    end: Optional[int] = field(default=None)
    parent: Optional[MemRegion] = field(default=None)

    def __eq__(self, other: MemRegion) -> bool:
        return (self.start == other.start) and (self.size == other.size)

    def __lt__(self, other: MemRegion) -> bool:
        if self.start == other.start:
            return self.size > other.size
        return self.start < other.start

    @property
    def size(self) -> int:
        return self.end + 1 - self.start if self.end else 1


class ReadOnly(MemRegion):
    pass


class ReadWrite(MemRegion):
    pass


class UNAVAILABLE(MemRegion):
    pass


class WriteProt(MemRegion):
    unprotect: Callable[[], bool] = lambda: False
    pass


@define
class HP_3457A:
    @frozen
    class HP_3457A_MEM_MAPS:
        BOARD_STR: ClassVar[str] = ""
        _REGIONS: ClassVar[Dict[str, MemRegion]] = {}

        @classmethod
        @property
        def REGIONS(cls) -> Dict[str, MemRegion]:
            if not cls._REGIONS:
                regions: List[Tuple[str, MemRegion]] = []
                for attr_name in dir(cls):
                    if attr_name == "REGIONS":
                        continue
                    attr = getattr(cls, attr_name)
                    if isinstance(attr, MemRegion):
                        regions.append((attr_name, attr))
                regions.sort(key=lambda r: r[1])
                cls._REGIONS = {key: region for key, region in regions}
            return cls._REGIONS

    class A1_03457_66501(HP_3457A_MEM_MAPS):
        U503: ClassVar[ReadOnly] = ReadOnly(
            desc="8KiB 8-bit NMOS ROM",
            start=0x6000,
            end=0x7FFF,
        )
        U502: ClassVar[ReadOnly] = ReadOnly(
            desc="32KiB 8-bit EPROM",
            start=0x8000,
            end=0xFFFF,
        )
        U506: ClassVar[ReadWrite] = ReadWrite(
            desc="2KiB 8-bit RAM",
            start=0x4800,
            end=0x4FFF,
        )
        U511: ClassVar[MemRegion] = MemRegion(
            desc="2KiB 8-bit SRAM, 0.5KiB protected",
            start=0x5000,
            end=0x57FF,
        )
        U511_RAM: ClassVar[ReadWrite] = ReadWrite(
            desc="1.5KiB 8-bit RAM in U511",
            start=0x5000,
            end=0x55FF,
            parent=U511,
        )
        U511_CAL_RAM: ClassVar[WriteProt] = WriteProt(
            desc="0.5KiB 8-bit CAL-RAM in U511",
            start=0x5600,
            end=0x57FF,
            parent=U511,
        )
        BOARD_STR: ClassVar[str] = "03457-66501"

    class A1_03457_66511(HP_3457A_MEM_MAPS):
        U602: ClassVar[ReadOnly] = ReadOnly(
            desc="64KiB 8-bit EPROM, 53KiB addressible",
            start=0x2000,
            end=0xFFFF,
        )
        U603: ClassVar[MemRegion] = MemRegion(
            desc="8KiB 8-bit SRAM, 8128 addressible, 0.5KiB protected,",
            start=0x40,
            end=0x1FFF,
        )
        U603_CAL_RAM: ClassVar[WriteProt] = WriteProt(
            desc="442 8-bit CAL-RAM in U603",
            start=0x40,
            end=0x1FF,
            parent=U603,
        )
        U603_RAM: ClassVar[ReadWrite] = ReadWrite(
            desc="8K 8-bit SRAM",
            start=0x200,
            end=0x1FFF,
            parent=U603,
        )
        BOARD_STR: ClassVar[str] = "03457-66511"

    @define
    class Errors:
        @frozen
        class Error:
            mask: int = field()
            txt: str = field(order=False)  # Don't use txt for __eq__ etc.

        HW: ClassVar[Error] = Error(
            mask=1, txt="Hardware error - check the auxiliary error register"
        )
        CALORACAL: ClassVar[Error] = Error(
            mask=2, txt="Error in the CAL or ACAL process"
        )
        TRIGTOOFAST: ClassVar[Error] = Error(mask=4, txt="Trigger too fast")
        SYNTAX: ClassVar[Error] = Error(mask=8, txt="Syntax error")
        UNKCMD: ClassVar[Error] = Error(mask=16, txt="Unknown command received")
        UNKPARAM: ClassVar[Error] = Error(mask=32, txt="Unknown parameter received")
        PARAMRNG: ClassVar[Error] = Error(mask=64, txt="Parameter out of range")
        REQPARAMMISS: ClassVar[Error] = Error(
            mask=128, txt="Required parameter missing"
        )
        PARAMIGN: ClassVar[Error] = Error(mask=256, txt="Parameter ignored")
        OUTOFCAL: ClassVar[Error] = Error(mask=512, txt="Out of calibration")
        AUTOCALREQ: ClassVar[Error] = Error(mask=1024, txt="Autocal required")

        _BY_MASK: ClassVar[Dict[int, Error]] = {}

        @classmethod
        @property
        def BY_MASK(cls) -> Dict[int, Error]:
            if not cls._BY_MASK:
                for attr_name in dir(cls):
                    if attr_name == "BY_MASK":
                        continue
                    attr = getattr(cls, attr_name)
                    if isinstance(attr, cls.Error):
                        cls._BY_MASK[attr.mask] = attr
            return cls._BY_MASK

        @classmethod
        def init_str(cls, error_reg_str: str) -> Set[HP_3457A.Errors.Error]:
            error_reg = int(
                float(error_reg_str)
            )  # HP 3457A returns reg as float string
            errors: Set[HP_3457A.Errors.Error] = set()
            for err_mask, err in cls.BY_MASK.items():
                if error_reg & err_mask:
                    errors.add(err)
            return errors

    class A1DetectionFailed(Exception):
        pass

    class RevDetectionFailed(Exception):
        pass

    inst: GPIBInstrument = field()
    a1: Type[HP_3457A_MEM_MAPS] = field()
    rev: Tuple[int, int] = field()

    PYVISA_GPIB_PATTERN: ClassVar[re.Pattern] = re.compile(r"GPIB\d::\d+::INSTR")

    _PEEK_PACK_F = struct.Struct("<h").pack

    @classmethod
    def select(cls, resource_name: str) -> HP_3457A:
        rm = pyvisa.ResourceManager()
        hp: GPIBInstrument = rm.open_resource(
            resource_name, write_termination="\r", read_termination="\r"
        )  # type: ignore
        hp.write("END ALWAYS")  # Make 3457A use EOI over GPIB
        hp.write("PRESET")  # Put into a known state and stop
        hp.write("ERR?")  # Clear error register
        # Testing existence of POKE command
        hp.write("POKE")
        err_str = hp.query("ERR?")
        errors = cls.Errors.init_str(err_str)
        logger.debug("ERR: %s", errors)
        if cls.Errors.UNKCMD in errors:
            a1 = HP_3457A.A1_03457_66501
        elif cls.Errors.REQPARAMMISS in errors:
            a1 = HP_3457A.A1_03457_66511
        else:
            raise cls.A1DetectionFailed(
                f"Errors Detected: {', '.join(f'{str(e)}' for e in errors)}"
            )
        rev_str = hp.query("REV?")
        rev = [int(float(s)) for s in rev_str.split(",")]
        if len(rev) != 2:
            raise cls.RevDetectionFailed(f"REV string {rev_str} could not be parsed.")
        else:
            rev = tuple(rev)
        return cls(inst=hp, a1=a1, rev=rev)

    def query(self, str: str) -> str:
        return self.inst.query(str)

    def read(self) -> str:
        return self.inst.read()

    def write(self, str: str) -> None:
        self.inst.write(str)

    def _peek_bytes(self, ptr: int) -> Tuple[int, int]:
        peek_instr = f"PEEK {ptr}"
        peek_val_short_raw = int(float(self.query(peek_instr)))
        ptr_incr_val, ptr_val = self._PEEK_PACK_F(peek_val_short_raw)
        logger.debug(
            "%s - 0x%04X: %02X %02X",
            peek_instr,
            ptr,
            ptr_val,
            ptr_incr_val,
        )
        return (ptr_val, ptr_incr_val)

    def dump(
        self,
        start: int,
        end: int,
        progress: Callable[[Sequence[int]], Iterable[int]] = lambda s: s,
    ) -> List[int]:
        dump_vals: List[int] = []
        for ptr in progress(range(start, end, 2)):
            ptr_val, ptr_incr_val = self._peek_bytes(ptr=ptr)
            dump_vals.append(ptr_val)
            dump_vals.append(ptr_incr_val)
        return dump_vals


# Function to Get MD5 Sum
def md5(fname) -> str:
    hash_md5 = hashlib.md5()
    with open(fname, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()
