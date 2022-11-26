# HP 3457A Arbitrary Memory Dumper
# Andrei Aldea 2018
# Asks for Beginning and End Adress in Decimal to Read
# Reads twice, does MD5 checksum of the two files created and tells user if they match

import hashlib
import re
from logging import getLogger
from typing import ClassVar, Dict, Self, Set, Tuple

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

    inst: GPIBInstrument = field()
    a1: int = field()
    rev: Tuple[int, int] = field()

    A1_03457_66501: ClassVar[int] = 1
    A1_03457_66511: ClassVar[int] = 2
    PYVISA_GPIB_PATTERN: ClassVar[re.Pattern] = re.compile(r"GPIB\d::\d+::INSTR")

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
        elif cls.Errors.REQPARAMMISS in errors:
            a1 = cls.A1_03457_66511
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


# Function to Get MD5 Sum
def md5(fname) -> str:
    hash_md5 = hashlib.md5()
    with open(fname, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()
