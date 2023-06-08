Update 8.6.2023:
- removed MQTT_AS.py due to memory leakage issues (latest version had similar problems)
- added mqtt-simple synchronous driver for MQTT updates
- reworked WIFICONN_AS.py driver, simplier and faster
- added display light poweron via transistor and screen timeout
- tested with esp32-ota-20230426-v1.20.0.bin

Update 20.10.2022:
- added average calculation for temp, rh and pressure (list of 20 values, pop last value out from the list when size 20)
- average calculation slows reading changes, but in other hand one or two sensor failures do not cause problems
- mqtt messages are now converted to str due to fact MQTT_AS calculates len of mqtt message, and if message contains float, it crashes
- shortened variable names due to memory limits (ILI display init typically fails due to memory shortage)
- gc.collect() and gc.threshold(gc.mem_free() // 4 + gc.mem_alloc()) repeated in the code
- added error solutions and now raise errors if display is broken etc
- fixed error with corrective values read from runtimeconfig.json, now corrective value is added to the values read from the sensors
- fixed tuple error in the date calculation
- removed unused colour codes from the Display class due to memory issues
- improved debug screen at REPL
- lowered MCU speed to 80 MHz, less heating


Update 11.10.2022:
- Added LCD backlight control. Use two transistors, PNP and NPN as a driver. Select proper GPIO (in the parameters.py now 27).
- Added MQTT SSL and BACKLIGHT_TIMEOUT parameters to the runtimeconfig.json

Update 10.10.2022:
- Reorganized the code, updated I2C to Soft2IC due to Micropython 1.19.1 requirements.
- Implemented better details screen activation procedures and checkups.


Update 7.2.2021:
- New case is OK, but I broke PMS7003 connector and it is 1.27 mm pitch. I have to wait pitch strip connector bar to arrive from China before I can finalize the project.
- BME280 in the lollipop seems to perform great, accuracy is now good.
- Video about case design https://www.youtube.com/watch?v=CMfNU1NC0Rs&feature=emb_logo


Update 6.2.2021:
- New case design for 3D printing at https://www.thingiverse.com/thing:4752043
- Drawing at https://gallery.autodesk.com/projects/152573/assets/580774/embed
- I try to avoid convection with a lollipop-like case for the BME280. Test results in a few days.

Update 4.2.2021 (project day 22): 
- First version of the case seems to work fine for MCU and Display. Display install is a bit complex.
- Thingsverse: https://www.thingiverse.com/thing:4748310/files
- Fusion360 drawing https://bit.ly/3cRUtZF
- Uptime now > 500 000 seconds. Today I have to rip off sensors and install to the case and check if the case performs well too.
- Video: https://youtu.be/wdtEFb3794w
- BME280 must be splitted to separate case, because the display and MCU heat warms up sensor > 6C. It seems that BME280 chip do not ventilate enough.

Update 30.01.2021:

Runtime now 171468 seconds, no single reboots. Code performs well.
- Fusion360 drawing for the the display at https://bit.ly/3ahuRlR
- Fusion360 drawing for the PMS7003 sensor at https://bit.ly/3j41YNR
- Fusion360 drawing for the MHZ19B sensor at https://bit.ly/3cqNshX
- ESP32 SMD and DevBoard drawings already in the same repository and at Thingsverse https://www.thingiverse.com/divergentti/designs


Update 29.01.2021:

Separated WifiConnect to own class as WIFICONN_AS.py. Do not try to transfer files with PyCharm to drivers directory! It does not change target directory \ to /.
Same with ampy, if you transder files, remember to use / instead of \. Example: ampy -p COM4 put drivers\WIFICONN_AS.py drivers/WIFICONN_AS.py works ok, but
if you use \, then you will see file in the root of filesystem named drivers\\WIFICONN_AS.py

Added Dew Point calculation to the main screen as well as altitude calculation. Changed white bottom line "touch and wait details" so that if Airqaulity is not ready, line do not show. This avoids null value screen, which is just skipped in the rotation loop if happens (try: expect: type error).

Added Sensor monitor, System monitor and Network monitor screen to the rotation.

MQTT listens broker uptime $SYS/broker/uptime messages and updates broker uptime value for the Network monitor screen.

REPL (and WebREPL) is silent if DEBUG_SCREEN_ACTIVE = 0.


Update 28.01.2021:

Strugled with mqtt client, because if you forget word "client" from async def mqtt_subscribe(client) sub, error message in MQTT_AS.py line 538 gave "function takes 0 positional arguments but 1 were given" error and I was too blind to see it. Now mqtt publish works fine and data can be collected to the inxludb and grafana. Continuing with screens. Available memory seems to hold somewhere in 20 000 range. 


27.01.2021.

This is first running version of indoor Airquality measurement device. 

Due to free ram issues variable names are refactored (shortened) and comments are removed from the code. I will update this README instead.

Operation:
- Hardware-related parameters are in the parameters.py. UART2 may have initialization problems if boot cause is power on boot. That is fixed in the code by deleting CO2 sensor object and re-creation of the object if bootcause was 1 = power on boot. For some reason 2 second pause is not enough, 5 seconds seems to work.
- Runtime-parameters are in runtimeconfig.json and my initial idea was to update this file so that user selections can be saved to the file. Now this file needs to be updated via WebREPl or via REPL.
- Network statup is asynhronous so that two SSID + PASSWORD combinations can be presented in the runtimeconfig.json. Highest rssi = signal strength AP is selected. Once network is connected = IP address is acquired, then script executes WebREPL startup and adjust time with NTPTIME. If network gets disconnected, script will redo network handshake.
- Measurement from all sensors are gathered in the background and values are filled into rows to be displayed.
- MQTT topics updates information to the broker and from broker to the InfluxDB and Grafana. 
- MQTT can be used to pick better correction multipliers for sensors.

Future:
- Add GPIO for the TFT panel LED control.
- Test if SD-slot can be used at the same time, with bit-banged softSPI for Touchscreen and hardware SPI for the SD-card.
- I try to add some trending, either so that trends are picked from Grafana as embedded graphics, or create some simple graphics, depending on free ram.
- Design case with Fusion360 to be printed with 3D-printer, adding proper air channels for sensors and perhaps litle Steveson's shield, which indoors is most likely not that important. BME280 sensor will be bottom, because heat from ESP32 SMD will go up. PMS7003 documentation recommends distance between floow and sensor > 20 cm, which means case shall be wall mounted. 
- Perhaps calculate better AirQuality etc information in the InfluxDB and return data back to device via MQTT.


Known issues:
- Due to memory allocation issues removed split screen to 4 parts, where from user was able to select next screen.
- Keyboard is not implemented, therefore touch just rotates detail screen (to be added more).
- Display update is slow due to framebuffer issue. During screen update availabe memory is low, may cause out of memory. I tried with Peter Hinch ILI9341 drivers, https://github.com/peterhinch/micropython-tft-gui and https://github.com/peterhinch/micropython-lcd160cr-gui but unfortunatelly with my knowledge I did not get driver working at all, resulting out of memory right in the class init. If you get them working, please, use those drivers instead of this slow driver.

Solved issues:
- Touchscreen gave strange x, y values: reason too high SPI-bus speed. Use minimum 1 MHz, maximum 2 MHz. This script uses 1.2MHz
- Toucscreen responded very slow to touch: bad DUPONT-connectors! 


Datasheets:
1. MH-Z19B CO2 NDIR sensor https://www.winsen-sensor.com/d/files/infrared-gas-sensor/mh-z19b-co2-ver1_0.pdf
2. BME280 Temp/Rh/Pressure sensor https://www.bosch-sensortec.com/products/environmental-sensors/humidity-sensors-bme280/
3. PMS7003 Particle sensor https://download.kamami.com/p564008-p564008-PMS7003%20series%20data%20manua_English_V2.5.pdf
4. ESP32 https://www.espressif.com/sites/default/files/documentation/esp32_datasheet_en.pdf

Libraries:
1. ILI9341 display rdagger / https://github.com/rdagger/micropython-ili9341/blob/master/ili9341.py
2. XGLCD fonts rdagger/ https://github.com/rdagger/micropython-ili9341/blob/master/xglcd_font.py
3. XPT2046 touchscreen  rdagger / https://github.com/rdagger/micropython-ili9341/blob/master/xpt2046.py
4. PMS7003_AS modified to asynchronous StreamReader method by Jari Hiltunen, 
   original Paweł Kucmus https://github.com/pkucmus/micropython-pms7003/blob/master/pms7003.py
5. MHZ19B_AS modified to asynchronous StreamWriter and Reader method by Jari Hiltunen, 
   original Dmytro Panin https://github.com/dr-mod/co2-monitoring-station/blob/master/mhz19b.py
6. MQTT_AS Peter Hinch / https://github.com/peterhinch/micropython-mqtt/blob/master/mqtt_as/mqtt_as.py

Micropython from https://micropython.org/ downloads https://micropython.org/download/ running esp32-idf4-20200902-v1.13.bin

AMPY tool for file transfers https://learn.adafruit.com/micropython-basics-load-files-and-run-code/install-ampy
