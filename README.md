# OpenSmartHome (in MicroPython and C/C++)
## Open-source smart-home project using ESP8266/ESP32 MicroPython. This project is WIP (work-in-progress).


## How to install?
- For ESP8266, you need to get a modified version of MicroPython (which provides bigger RAM and higher PWM frequency). Clone and build `https://github.com/xuancong84/micropython.git` . For ESP32, you can use open-build MicroPython directly, but you might need to modify MicroPython codes correspondingly.
- Download the PCB Gerber/json, and edit the PCB layout correspondingly according to your need.

## How to use?
- All customizable controls, PIN assignments, initialization routines, control codes are specified in `rc-codes.txt`.

## Initialization:
- You can specify initialization in `__preinit__`, `__init__`, and `__postinit__`.
- `__preinit__` (if present, must be on the 1st row) contains codes that are executed before main code is loaded (which can take 1-3 seconds), if you want to define some quick power-on behaviour, e.g., turn on all devices upon switching on regardless of any sensor status, put them here.
- `__init__` contains codes that are executed after main code is loaded, but before object creation (which depends on PIN assignment) and connecting to Wifi. You can put PIN definitions and initialization here.
- `__postinit__` contains codes that are executed after Wifi is connected, just before entering the main loop. You can put your Timers here (ESP8266 crashes if you define Timers before connecting to Wifi).

# OpenSmartLight (C/C++ deprecated)
Open-source smart-light sensor module for ceiling lighting control

![PCB layout PNG](/PCB/PCB.png)
![PCB soldered PNG](/PCB/PCB-soldered.jpg)

This module uses the latest 24GHz microwave micro-motion sensor (HLK-LD1115H) to sense human presence and uses LGT8F328P (mini or LED version) or NodeMCU (Wifi version) as microcontroller.
When in the dark, whenever human is present, it turns on the ceiling light. That is the standard mini version.

LED version:
- on top of the mini version, but in the mid-night, it will (by default) smoothly turn on the LED instead, so that it will not disturb your sleep.

Wifi version:
- on top of the LED version, it can connect to Wifi and adjust settings (or control lighting) from the web browser.
- you can put in your Wifi's SSID, password, and other configuration in secret.h and rebuild
- without Wifi credentials, it will create a Wifi hotspot with SSID=OpenSmartLight and a captive portal to redirect to the main config page
- you can save all settings in EEPROM to survive system restart, but it cannot survive reflash
- once installed onto the ceiling, developers can upload updated code by OTA firmware update, without flashing via USB

![Web-UI PNG](/web-ui.png)

All source codes and PCB layout files (EasyEDA/Gerber) are available. You can send for PCB fabrication.
