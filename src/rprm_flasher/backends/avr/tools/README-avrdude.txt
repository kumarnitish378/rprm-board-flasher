avrdude, redistributed here in binary form
==========================================

Version:  8.0-arduino.1
Files:    avrdude.exe, avrdude.conf
Licence:  GNU General Public License - full text in LICENSE.txt beside this file

This is the unmodified Windows build that ships with the Arduino IDE, taken
from the Arduino15 tool packages. Nothing about it has been patched or
recompiled; this project only invokes it as a separate process.

The GPL requires that anyone receiving these binaries can get the corresponding
source. It is published by the avrdude project at:

    https://github.com/avrdudes/avrdude
    https://github.com/avrdudes/avrdude/releases/tag/v8.0

and the Arduino packaging of it at:

    https://github.com/arduino/avrdude-build

Because this project runs avrdude as a separate executable rather than linking
against it, the two are aggregated works: avrdude remains under the GPL, and
this project's own code is not placed under the GPL by including it.
