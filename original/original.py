# HP 3457A Arbitrary Memory Dumper
# Andrei Aldea 2018
# Asks for Beginning and End Adress in Decimal to Read
# Reads twice, does MD5 checksum of the two files created and tells user if they match

import hashlib
import time

import pyvisa as visa  # Minor change by Dr. Matthew Swabey to match current visa package name

rm = visa.ResourceManager()
inst = rm.open_resource("GPIB0::22::INSTR")
inst.write("TRIG 4")  # Freeze instrument so we can read from it


def peek_memory(f):
    for x in range(
        int(start_adress), int(end_adress)
    ):  # OR 64 to 512 for older ROM versions? 20480 to 22528 for newer

        try:
            the_str = "PEEK " + str(x)
            print(the_str)
            inst.write(the_str)
            data = inst.read_bytes(
                14
            )  # Read data 14  bytes at a time... ~ what the insrument returns
            # NOTE: Instrument always returns Engineering notation... so convert to  float then Int... 'cause why not.
            string_data = (
                str(data).partition("'")[2].partition("'")[0] + "\n"
            )  # Split weird formatting and add a newline
            f.write(
                str(x) + ": " + str(int(float(string_data))) + "\n"
            )  # Write it's float equivalent to disk
            print(
                str(string_data) + " Or Decimal: " + str(int(float(string_data)))
            )  # Print what was written
            pass
        except:
            print("Couldn't read after " + the_str)
            f.write("THIS IS BROKEN")
            f.close()
    f.close()


# Function to Get MD5 Sum
def md5(fname):
    hash_md5 = hashlib.md5()
    with open(fname, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


inst.write("ID?")  # Ask the instrument what it is
print(
    (
        str(inst.read_bytes(9)).partition("'")[2].partition("'")[0].partition("A")[0]
        + " Detected"
    )
)  # Print instrument response

start_adress = input("Memory Start Adress (64 or 20480 reccomended): ")
end_adress = input("End Adress(512 or 22528 recommended, 65535 max): ")

# First Checksum

fname_1 = "3457_DUMP_" + str(int(time.time())) + ".txt"
f = open(fname_1, "w")
peek_memory(f)
checksum1 = md5(fname_1)

# Second Checksum
fname_2 = "3457_DUMP_" + str(int(time.time())) + ".txt"
f = open(fname_2, "w")
peek_memory(f)
checksum2 = md5(fname_2)

if checksum1 == checksum2:
    print("Success!")
else:
    print("FAILED. MD5 Sums of Two Reads do not Match!")
    print(fname_1 + " MD5: " + str(checksum1))
    print(fname_2 + " MD5: " + str(checksum2))
