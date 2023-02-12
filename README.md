# OpenSmartLight
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
