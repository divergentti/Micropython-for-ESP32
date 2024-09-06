6.9.2024:
- New PMS9103M arrived, but now AQ index is calculated, because PM-values are read, but they keep low and no PCNT
- Reworked the main.py
- Reworked PMS9103M_as.py
- Waiting advice from manufacturer. Perhaps Aliexpress sell some fake sensors?
Data received: bytearray(b'B')
Data received: bytearray(b'M')
Data received: bytearray(b'\x00\x1c\x00\x02\x00\x04\x00\x05\x00\x02\x00\x04\x00\x05\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xc1')
Raw data received: bytearray(b'\x00\x1c\x00\x02\x00\x04\x00\x05\x00\x02\x00\x04\x00\x05\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xc1')
PMS Read at 778944757, data: {'PM2_5': 4, 'PM1_0_ATM': 2, 'PM10_0_ATM': 5, 'VERSION': 0, 'ERROR': 0, 'CHECKSUM': 193, 'PM1_0': 2, 'PM10_0': 5, 'PM2_5_ATM': 4, 'PCNT_0_5': 0, 'PCNT_5_0': 0, 'FRAME_LENGTH': 28, 'PCNT_2_5': 0, 'PCNT_1_0': 0, 'PCNT_10_0': 0, 'PCNT_0_3': 0}

18.8.2024:
- Trying to find out is PMS9103M issue with a hardware or my driver. Tested with passive and active modes. Active mode used in the PMS9103M_AS.py driver.
- Debug explained (https://evelta.com/content/datasheets/203-PMS9003M.pdf):
  - PMS reader data b'B' = start byte1 0x42
  - PMS reader data b'M' = start byte2 0x4d and after this comes frame we are interested in
  - PMS reader data b'\x00\x1c\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x1b\x00\n\x00\x00\x00\x00\x00\x00\x00\x00\x13\x00\x00\xe3'
  - first two bytes should be frame length of data and check bytes
  - last two bytes are checksum low and high
  - practically I see that only PCNT < 0.3 and PCNT < 0.5 are read correctly, so the frame is messed up
  - for the Air Quality Index weed need ATM-values, which are always 0
  - following do not work
    

```yaml annotate
from machine import UART, Pin
import utime
import uasyncio as asyncio

class PMS:
    CMD_WAKEUP = bytearray([0x42, 0x4d, 0xe4, 0x00, 0x01, 0x01, 0x74])
    CMD_SLEEP = bytearray([0x42, 0x4d, 0xe4, 0x00, 0x00, 0x01, 0x73])
    CMD_PASSIVE_MODE = bytearray([0x42, 0x4d, 0xe1, 0x00, 0x00, 0x01, 0x70])
    CMD_READ_PASSIVE = bytearray([0x42, 0x4d, 0xe2, 0x00, 0x00, 0x01, 0x71])

    START_BYTE_1 = 0x42
    START_BYTE_2 = 0x4d
    PM1_OFFSET = 6
    PM2P5_OFFSET = 8
    PM10_OFFSET = 10
    PM1_ATM_OFFSET = 12
    PM2P5_ATM_OFFSET = 14
    PM10_ATM_OFFSET = 16
    PCNT0_3_OFFSET = 18
    PCNT0_5_OFFSET = 20
    PCNT1_0_OFFSET = 22
    PCNT2_5_OFFSET = 24
    PCNT5_0_OFFSET = 26
    PCNT10_OFFSET = 28
    VERSION_OFFSET = 30
    ERROR_OFFSET = 32
    MAX_DATA_LENGTH = 32
    READ_INTERVAL = 10

    def verify_checksum(self, frame):
        checksum = sum(frame[:-2]) & 0xFFFF
        return (frame[-2] << 8 | frame[-1]) == checksum

    async def writer(self, data):
        self.sensor.write(data)
        await asyncio.sleep(0.1)

    def __init__(self, rxpin=16, txpin=17, uart=2):
        self.sensor = UART(uart, baudrate=9600, bits=8, parity=None, stop=1, rx=Pin(rxpin), tx=Pin(txpin))
        self.buffer = bytearray(self.MAX_DATA_LENGTH)
        self.pms_dictionary = None
        self.last_read = 0
        self.startup_time = utime.time()
        self.read_interval = 30
        self.debug = False
        asyncio.run(self.wake_up())
        asyncio.run(self.enter_passive_mode())

    async def read_pm_values(self):
        port = asyncio.StreamReader(self.sensor)
        await self.writer(self.CMD_READ_PASSIVE)
        raw_data = await port.readexactly(self.MAX_DATA_LENGTH * 2)  # read more data to find the start bytes
        if self.debug:
            print("Raw data: %s" % raw_data)

        # Look for the start bytes
        start_idx = raw_data.find(b'\x42\x4d')
        if start_idx == -1 or start_idx + self.MAX_DATA_LENGTH > len(raw_data):
            if self.debug:
                print("Error: Start bytes not found or incomplete data frame.")
            return False

        self.buffer = raw_data[start_idx:start_idx + self.MAX_DATA_LENGTH]
        if self.debug:
            print("PMS buffer: %s" % self.buffer)

        if self.verify_checksum(self.buffer):
            pm1 = self.buffer[self.PM1_OFFSET] << 8 | self.buffer[self.PM1_OFFSET + 1]
            pm1_atm = self.buffer[self.PM1_ATM_OFFSET] << 8 | self.buffer[self.PM1_ATM_OFFSET + 1]
            pm2_5 = self.buffer[self.PM2P5_OFFSET] << 8 | self.buffer[self.PM2P5_OFFSET + 1]
            pm2_5_atm = self.buffer[self.PM2P5_ATM_OFFSET] << 8 | self.buffer[self.PM2P5_ATM_OFFSET + 1]
            pm10 = self.buffer[self.PM10_OFFSET] << 8 | self.buffer[self.PM10_OFFSET + 1]
            pm10_atm = self.buffer[self.PM10_ATM_OFFSET] << 8 | self.buffer[self.PM10_ATM_OFFSET + 1]
            pcnt0_3 = self.buffer[self.PCNT0_3_OFFSET] << 8 | self.buffer[self.PCNT0_3_OFFSET + 1]
            pcnt0_5 = self.buffer[self.PCNT0_5_OFFSET] << 8 | self.buffer[self.PCNT0_5_OFFSET + 1]
            pcnt1_0 = self.buffer[self.PCNT1_0_OFFSET] << 8 | self.buffer[self.PCNT1_0_OFFSET + 1]
            pcnt2_5 = self.buffer[self.PCNT2_5_OFFSET] << 8 | self.buffer[self.PCNT2_5_OFFSET + 1]
            pcnt5_0 = self.buffer[self.PCNT5_0_OFFSET] << 8 | self.buffer[self.PCNT5_0_OFFSET + 1]
            pcnt10 = self.buffer[self.PCNT10_OFFSET] << 8 | self.buffer[self.PCNT10_OFFSET + 1]
            version = self.buffer[self.VERSION_OFFSET] << 8 | self.buffer[self.VERSION_OFFSET + 1]
            error = self.buffer[self.ERROR_OFFSET] << 8 | self.buffer[self.ERROR_OFFSET + 1]

            self.pms_dictionary = {
                'PM1_0': pm1,
                'PM2_5': pm2_5,
                'PM10_0': pm10,
                'PM1_0_ATM': pm1_atm,
                'PM2_5_ATM': pm2_5_atm,
                'PM10_0_ATM': pm10_atm,
                'PCNT_0_3': pcnt0_3,
                'PCNT_0_5': pcnt0_5,
                'PCNT_1_0': pcnt1_0,
                'PCNT_2_5': pcnt2_5,
                'PCNT_5_0': pcnt5_0,
                'PCNT_10_0': pcnt10,
                'VERSION': version,
                'ERROR': error
            }
            self.last_read = utime.time()
            return True
        else:
            if self.debug:
                print("Error: Incomplete data frame or checksum mismatch.")
            return False

    async def wake_up(self):
        await self.writer(self.CMD_WAKEUP)

    async def sleep(self):
        await self.writer(self.CMD_SLEEP)

    async def enter_passive_mode(self):
        await self.writer(self.CMD_PASSIVE_MODE)

    async def read_async_loop(self):
        while True:
            status = await self.read_pm_values()
            if self.debug:
                print("PMS read status: %s" % status)
            await asyncio.sleep(self.READ_INTERVAL)

# Initialize PMS sensor with appropriate UART pins
pms_sensor = PMS(rxpin=16, txpin=17, uart=2)

# Run the asynchronous read loop
asyncio.run(pms_sensor.read_async_loop())
                      
'''

11.8.2024:
- added debugging option for PMS9103M and MHZ drivers
- added active mode command for PMS9103M
- still issues with PMS values, keeps 0 ... perhaps faulty sensor

10.8.2024:
- added startup timer to PMS9103M_AS.py
- fixed parameters.py UART ports
- reorganized sensor init etc in main.py, checking is air quality index starts working now ... for some reason very low particle readings

1.8-10.8.2024:
- no single crash except air quality index did not show up = PMS9103M reading issues.

1.8.2024:
- reworked watchdog and display items

28.07.2024:
- added watchdog module to check if values do not change (= sensor seems to be ok, but values not)
- added UART re-inits (del co2s and pms objects and re-create) in case of cold boot
- Issue with webrepl and ntptime, needs in depht debugging

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
- Total about: 39€

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
- PIN1 = VCC = 5V
- PIN2 = GND
- PIN3 = SET (TTL 3.3V = normal working, GND = sleeping) = 4 * (not needed)
- PIN4 = RXD (3.3V) = 17
- PIN5 = TXD (3.3V) = 16
- PIN6 = RESET (not needed) 
- 7,8 N/C. * = pullup

MH-Z19B databseet: https://www.winsen-sensor.com/d/files/infrared-gas-sensor/mh-z19b-co2-ver1_0.pdf

Pinout (do not use 2,3 tx/rx otherwise pytool fails):
- Vin = 5V
- GND = GND
- RX = 32
- TX = 33

Program read sensor values once per second, rounds them to 1 decimal with correction values, then calculates averages.
Averages are sent to the MQTT broker.

For webrepl, remember to execute import webrepl_setup one time.

Asyncronous code.
