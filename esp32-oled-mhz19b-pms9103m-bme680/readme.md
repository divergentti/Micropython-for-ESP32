26.07.2024: OLED display started working, had configuration typo. Not yet complete, but getting closer.

Changes:
- added proper error logging to a csv-file
- fixed variable and classnames
- updated WIFICONN_AS.py
- reworked MQTT update
- reworked globals
- reworked CLI monitoring

Issues and not yet complete:
- PMS9103M seems to give a few particle counts, but nothing more. Perhaps UART issue.
- AirQuality index calculation do not get enough data
- Calibrations

25.07.2024 first attempts to make program

Enclosure and Fusion360 drawing for this gadget at https://www.thingiverse.com/thing:6707670

Components:
- 1.3 inch OLED module white/blue SPI/IIC I2C Communicate color 128X64 1.3 inch OLED LCD LED Display Module 1.3" OLED module (2.24€)
- ESP32-DevKitC core board ESP32 V4 development board ESP32-WROOM-32D/U (3.32€)
- BME680 Digital Temperature Humidity Pressure Sensor CJMCU-680 High Altitude Sensor Module Development Board (6.64€)
- MH-Z19B IR Infrared CO2 Sensor Carbon Dioxide Gas Sensor Module CO2 Monitor 400-5000 0-5000ppm UART PWM (15.31€)
- PMS9103M PM2.5 Laser Dust Particle Sensor Module Detects PM2S-3 Indoor Gas Air Quality Detection PMS9003M Plantower For Purifier (11.71€)
Total about: 39€

Initial code. The particle sensor, CO2 sensor and BME680 seems to work, but I broke my last OLED display and need to wait for new to arrive. This was not true. If asynchronous display update has errors (like Nonetype), display is black. 

Command i2c.scan() finds the display, but backlight did not illuminate due to error in the code.
[60, 119]

These scripts are used for I2C connected OLED display, BME680 temperature/rh/pressure/voc sensor
MH-Z19B CO2 NDIR-sensor, PMS9103M particle sensor.

Values could be transferred by MQTT to the MQTT broker and from the broker to the Influxdb etc.

I2C for the OLED and BME680 are connected to SDA = Pin21 and SCL (SCK) = Pin22.
Use command i2c.scan() to check which devices respond from the I2C channel.

MH-Z19B and PMS9103M are connected to UART1 and UART2. Check parameters.py

PMS9103M datasheet https://evelta.com/content/datasheets/203-PMS9003M.pdf

Pinout (ledge upwards, PIN1 = right):
PIN1 = VCC = 5V
PIN2 = GND
PIN3 = SET (TTL 3.3V = normal working, GND = sleeping) = 4 * (not needed)
PIN4 = RXD (3.3V) = 17
PIN5 = TXD (3.3V) = 16
PIN6 = RESET (not needed) 
7,8 N/C. * = pullup

MH-Z19B databseet: https://www.winsen-sensor.com/d/files/infrared-gas-sensor/mh-z19b-co2-ver1_0.pdf

Pinout (do not use 2,3 tx/rx otherwise pytool fails):
Vin = 5V
GND = GND
RX = 32
TX = 33

Program read sensor values once per second, rounds them to 1 decimal with correction values, then calculates averages.
Averages are sent to the MQTT broker.

For webrepl, remember to execute import webrepl_setup one time.

Asyncronous code.
