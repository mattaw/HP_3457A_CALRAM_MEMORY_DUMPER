# HP 3457A Arbitrary Memory Dumper
# Andrei Aldea 2018
# Asks for Beginning and End Adress in Decimal to Read
# Reads twice, does MD5 checksum of the two files created and tells user if they match

import hashlib
import re
import struct
from logging import getLogger
from typing import (
    Callable,
    ClassVar,
    Dict,
    Iterable,
    List,
    Optional,
    Self,
    Sequence,
    Set,
    Tuple,
)

import pyvisa
from attr import define, field, frozen
from pyvisa.resources import GPIBInstrument

logger = getLogger(__name__)


@define
class HP_3457A:
    @frozen
    class Errors:
        @frozen
        class Error:
            mask: int = field()
            txt: str = field(order=False)  # Don't use txt for __eq__ etc.

        CTE = ClassVar[Error]

        HW: CTE = Error(
            mask=1, txt="Hardware error - check the auxiliary error register"
        )
        CALORACAL: CTE = Error(mask=2, txt="Error in the CAL or ACAL process")
        TRIGTOOFAST: CTE = Error(mask=4, txt="Trigger too fast")
        SYNTAX: CTE = Error(mask=8, txt="Syntax error")
        UNKCMD: CTE = Error(mask=16, txt="Unknown command received")
        UNKPARAM: CTE = Error(mask=32, txt="Unknown parameter received")
        PARAMRNG: CTE = Error(mask=64, txt="Parameter out of range")
        REQPARAMMISS: CTE = Error(mask=128, txt="Required parameter missing")
        PARAMIGN: CTE = Error(mask=256, txt="Parameter ignored")
        OUTOFCAL: CTE = Error(mask=512, txt="Out of calibration")
        AUTOCALREQ: CTE = Error(mask=1024, txt="Autocal required")

        @classmethod
        def by_mask(cls) -> Dict[int, Error]:
            return {
                err.mask: err for err in cls.__dict__.values() if type(err) is cls.Error
            }

        @classmethod
        def init_str(cls, error_reg_str: str) -> Set[Self]:
            error_reg = int(
                float(error_reg_str)
            )  # HP 3457A returns reg as float string
            errors = set()
            for err_mask, err in cls.by_mask().items():
                if error_reg & err_mask:
                    errors.add(err)
            return errors

    class A1DetectionFailed(Exception):
        pass

    class RevDetectionFailed(Exception):
        pass

    @frozen
    class MemoryMap:
        type_: int = field()
        desc: str = field()
        read_: Tuple[int, int] = field()  # Start ADDR, Size
        write: Optional[Tuple[int, int]] = field(default=None)
        protr: Optional[Tuple[int, int]] = field(default=None)
        protw: Optional[Tuple[int, int]] = field(default=None)

        ROM: ClassVar[int] = 1
        RAM: ClassVar[int] = 2
        PROTECTED: ClassVar[int] = 3

    inst: GPIBInstrument = field()
    a1: int = field()
    rev: Tuple[int, int] = field()
    memory_map: Dict[str, MemoryMap]

    A1_03457_66501: ClassVar[int] = 1
    A1_03457_66511: ClassVar[int] = 2
    PYVISA_GPIB_PATTERN: ClassVar[re.Pattern] = re.compile(r"GPIB\d::\d+::INSTR")

    MEMORY_MAPS: ClassVar[Dict[int, Dict[str, MemoryMap]]] = {
        A1_03457_66501: {
            # Note: No POKE command on this version, so read only.
            # Address    AAAA_AAAA_AAAA_AAAA
            # Bus        1111_11
            # Signal     5432_1098_7654_3210
            "U503": MemoryMap(
                type_=MemoryMap.ROM,
                desc="8K 8-bit NMOS ROM",
                read_=(0b0110_0000_0000_0000, 0x2000),
            ),
            "U502": MemoryMap(
                type_=MemoryMap.ROM,
                desc="32K 8-bit EEPROM",
                read_=(0b1000_0000_0000_0000, 0x8000),
            ),
            "U506": MemoryMap(
                type_=MemoryMap.RAM,
                desc="2K 8-bit RAM",
                read_=(0b0100_1000_0000_0000, 0x0800),
                # write=(0b0100_1000_0000_0000, 0x0800),
                write=None,
            ),
            "U511": MemoryMap(
                type_=MemoryMap.RAM,
                desc="1.5K 8-bit RAM and 0.5K 8-bit CAL-RAM",
                read_=(0b0101_0000_0000_0000, 0x0600),
                # write=(0b0101_0000_0000_0000, 0x0600),
                write=None,
                protr=(0b0101_0110_0000_0000, 0x0200),
                # protw=(0b0101_0110_0000_0000, 0x0200),
                protw=None,
            ),
        }
    }

    _PEEK_PACK_F = struct.Struct("<h").pack

    @classmethod
    def select(cls, resource_name: str) -> Self:
        rm = pyvisa.ResourceManager()
        hp: GPIBInstrument = rm.open_resource(
            resource_name, write_termination="\r", read_termination="\r"
        )  # type: ignore
        hp.write("END ALWAYS")  # Make 3457A use EOI over GPIB
        hp.write("PRESET")  # Put into a known state and stop
        hp.write("ERR?")  # Clear error register
        # Testing existence of POKE command
        hp.write("POKE")
        errors = cls.Errors.init_str(hp.query("ERR?"))
        logger.debug("ERR: %s", errors)
        if cls.Errors.UNKCMD in errors:
            a1 = cls.A1_03457_66501
            memory_map = cls.MEMORY_MAPS[a1]
        elif cls.Errors.REQPARAMMISS in errors:
            a1 = cls.A1_03457_66511
            memory_map = cls.MEMORY_MAPS[a1]
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
        return cls(inst=hp, a1=a1, rev=rev, memory_map=memory_map)

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
        size: int,
        progress: Callable[[Sequence[int]], Iterable[int]] = lambda s: s,
    ) -> List[int]:
        dump_vals: List[int] = []
        for ptr in progress(range(start, start + size, 2)):
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
