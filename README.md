# HP 3457A CalRAM Memory Dumper

## Introduction

A python script to dump arbitrary memory ranges of [HP 3457A](https://www.keysight.com/us/en/product/3457A/digital-multimeter.html) digital multimeters, particularly the CALRAM and ROMs.

There are two main "generations" of the HP 3457A which have different A1 Digital Assembly / Main Controller PCBs:

  1. The original model with Main Controller 03457-66501, CALRAM is 512 bytes of U511: 0x5600-0x57FF
  2. Later ones have Main Controller 03457-66511, CALRAM is 442 bytes of U603: 40-1FF
  
They are substanially different in how their memory is arranged both programatically and physically, and only the later models (66511) ships with a `POKE` command in the firmware to write memory. This means any upgrade of the 66501 controller from battery backed SRAM to non-volatile FRAM require the FRAM to be programmed outside of the meter.

The later models still require [a hardware modification](https://www.eevblog.com/forum/metrology/dumping-cal-ram-of-a-hp3457a/msg1419641/#msg1419641) to program the calibration memory due to a hardware lock protecting the calibration addresses in the SRAM. The hardware lock is not currently defeatable in software - if someone knows the method, or someone familiar with the Motorola 6809 microprocessor programming/reset please contact me, I would love to add it.

## Thanks

Based on the eevBlog post by Andrei Aldea in 2018, https://www.eevblog.com/forum/metrology/dumping-cal-ram-of-a-hp3457a/msg2019064/#msg2019064.

The knowledge and dumps this project is built on come from the excellent work done on the eevBlog forum topic [Dumping and restoring the CAL RAM of an HP3457A](https://www.eevblog.com/forum/metrology/dumping-cal-ram-of-a-hp3457a/25/). Particular thanks go to eevBlog forum posters:

| Username | Contribution |
| -------- | ------------ |
| [0xfede](https://www.eevblog.com/forum/profile/?u=99568) | The original eevBlog poster, disassembly of HP 3457A firmware that found the `POKE` & `PEEK` commands, hardware mod to avoid the hardware NVRAM lock, C# program to dump and restore the CALRAM, full dump from his HP 3457A and so much more. |
| [Wim13](https://www.eevblog.com/forum/profile/?u=36372) | Detailed the addresses and other information between the two different models clearly. Binary dump of all Model 1 RAM & ROM |
| [dl1640](https://www.eevblog.com/forum/profile/?u=127671) | 2018-07-30 Model 2 CALRAM dump |
| [Tryer](https://www.eevblog.com/forum/profile/?u=652380) | 2020-05-20 Model 2 CALRAM bin dump |

... and the many more members of the eevBlog forum who have contributed. If you feel you have been left out, please send me a message or PR to add you to the table.

## Requirements

  1. This project requires an IVI compatible GPIB bus connection to the HP 3457A
  2. [PyVISA](https://github.com/pyvisa/pyvisa) available through PyPI via `python -m pip install pyvisa`
  3. PyVISA setup and configured with your GPIB adapter. Please see that project's documentation first
