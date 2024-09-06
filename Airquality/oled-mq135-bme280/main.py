"""
This script is used for I2C connected OLED display, BME280 or DHT22 (AM2302) sensor and MQ135 sensor.
If you use DMP280, you need to have Rh from other sensor, like DHT22.

Values could be transferred by MQTT to the MQTT broker and from the broker to the Influxdb etc.

The MQ135-sensor VCC is 5 volts. Values are read from the AO (Analog Out) pin.
Analog Out (AO) is too high as default. ESP32 ADC (Analog to DC converter) read values 0 to 1 volts.
Over 1 volt gives value 4095. You need a resistor splitter for readings.
Use 47k resistor from MQ135 AO pin to 10K resistor, which other end is connected to GND.

MQ135 sensor data:
    - Rs 30 KOhm - 200 KOhm
    - RL = 20 KOhm
    - Ro = 100 ppm NH3 clear air
    - O2 standard 21 %, Temp 20C, Rh 65 %
    - Rh delta Rh and temp: Rs/Ro = 1 (20C/33 % Rh), Rs/Ro = 1.7 (-10C/33 % Rh)
    - Rh 33 % -> 85 % delta Rs/Ro = 0.1
    - Scope NH3 = 10 - 300 ppm
    - Bentsen 10 - 1000 ppm
    - Alcohol 10 - 300 ppm
    - For proper calculation you need temperature and Rh value from other sensor, like BME280, DHT22 etc.

If the MQ135 board has 102 (1k) load resistor in the middle on top (RL), it does not work for CO2!
- solder out the 1k resistor and replace with 20k (20 000) resistor
- if you use another ohms, change in runtimeconfig.json (10 = 10kOhm, 20 = 20kOhm)
- as default, MQ135.py attennuates signal by 11db.

Preheating time is 24 hours! After the 24 hours preheat process, check what console says about corrected RZERO and
use that value in runtimeconfig.json.

MQ135 is connected per parameters.py to Pin34 and in MQ135.py attennuated 11db
DHT22 (AM2302) is connected to Pin23
I2C for the OLED and BME280 (or BMP280) is connected to SDA = Pin21 and SCL = Pin22.
Use command i2c.scan() to check which devices respond from the I2C channel.

Program read sensor values once per second, rounds them to 1 decimal with correction values, then calculates averages.
Averages are sent to the MQTT broker.

Touch is enabled so that you can use any wire to activate the OLED display.

Asyncronous code. Tested with micropython 1.19.1, DHT22 and BMP280

For webrepl, remember to execute import webrepl_setup one time.

Version 0.3 Jari Hiltunen - 19.10.2022

"""


from machine import SoftI2C, Pin, freq, reset, ADC, TouchPad
import uasyncio as asyncio
from utime import time, mktime, localtime, sleep
import gc
import network
import drivers.MQ135 as CO2SENSOR
import drivers.WIFICONN_AS as WIFINET
import drivers.BME280_float as BmESensor
import drivers.SH1106 as OLEDDISPLAY
gc.collect()
from json import load
import esp32
import dht
from drivers.MQTT_AS import MQTTClient, config
gc.collect()

# Globals
mqtt_up = False
broker_uptime = 0
co2_average = None
temp_average = None
rh_average = None
BME280_sensor_faulty = False
BME280_sensor_type = "BME280"
MQ135_sensor_faulty = False
DHT22_sensor_faulty = False

try:
    f = open('parameters.py', "r")
    from parameters import I2C_SCL_PIN, I2C_SDA_PIN, MQ135_AO_PIN, DHT_PIN, TOUCH_PIN
    f.close()
except OSError:  # open failed
    print("parameter.py-file missing! Can not continue!")
    raise

try:
    f = open('runtimeconfig.json', 'r')
    with open('runtimeconfig.json') as config_file:
        data = load(config_file)
        f.close()
        SSID1 = data['SSID1']
        SSID2 = data['SSID2']
        PASSWORD1 = data['PASSWORD1']
        PASSWORD2 = data['PASSWORD2']
        MQTT_SERVER = data['MQTT_SERVER']
        MQTT_PASSWORD = data['MQTT_PASSWORD']
        MQTT_USER = data['MQTT_USER']
        MQTT_PORT = data['MQTT_PORT']
        MQTT_USE_SSL = data['MQTT_SSL']
        MQTT_INTERVAL = data['MQTT_INTERVAL']
        CLIENT_ID = data['CLIENT_ID']
        TOPIC_ERRORS = data['TOPIC_ERRORS']
        WEBREPL_PASSWORD = data['WEBREPL_PASSWORD']
        NTPSERVER = data['NTPSERVER']
        DHCP_NAME = data['DHCP_NAME']
        START_WEBREPL = data['START_WEBREPL']
        START_NETWORK = data['START_NETWORK']
        START_MQTT = data['START_MQTT']
        SCREEN_UPDATE_INTERVAL = data['SCREEN_UPDATE_INTERVAL']
        DEBUG_SCREEN_ACTIVE = data['DEBUG_SCREEN_ACTIVE']
        SCREEN_TIMEOUT = data['SCREEN_TIMEOUT']
        BACKLIGHT_TIMEOUT = data['BACKLIGHT_TIMEOUT']
        TOPIC_TEMP = data['TOPIC_TEMP']
        TOPIC_RH = data['TOPIC_RH']
        TOPIC_PRESSURE = data['TOPIC_PRESSURE']
        TOPIC_CO2 = data['TOPIC_CO2']
        TEMP_THOLD = data['TEMP_TRESHOLD']
        TEMP_CORRECTION = data['TEMP_CORRECTION']
        RH_THOLD = data['RH_TRESHOLD']
        RH_CORRECTION = data['RH_CORRECTION']
        P_THOLD = data['PRESSURE_TRESHOLD']
        CO2_CORRECTION = data['CO2_CORRECTION']
        PRESSURE_CORRECTION = data['PRESSURE_CORRECTION']
        MQ135_RESISTOR = data['MQ135_RESISTOR']
        MQ135_RZERO = data['MQ135_RZERO']
except OSError:
    print("Runtime parameters missing. Can not continue!")
    sleep(30)
    raise


def resolve_date():
    # For Finland
    (year, month, mdate, hour, minute, second, wday, yday) = localtime()
    weekdays = ['Ma', 'Ti', 'Ke', 'To', 'Pe', 'La', 'Su']
    summer_march = mktime((year, 3, (14 - (int(5 * year / 4 + 1)) % 7), 1, 0, 0, 0, 0))
    winter_december = mktime((year, 10, (7 - (int(5 * year / 4 + 1)) % 7), 1, 0, 0, 0, 0))
    if mktime(localtime()) < summer_march:
        dst = localtime(mktime(localtime()) + 7200)
    elif mktime(localtime()) < winter_december:
        dst = localtime(mktime(localtime()) + 7200)
    else:
        dst = localtime(mktime(localtime()) + 10800)
    (year, month, mdate, hour, minute, second, wday, yday) = dst
    day = "%s.%s.%s" % (mdate, month, year)
    hours = "%s:%s:%s" % ("{:02d}".format(hour), "{:02d}".format(minute), "{:02d}".format(second))
    return day, hours, weekdays[wday]


class Displayme(object):

    def __init__(self, width=16, rows=6, lpixels=128, kpixels=64):
        self.rows = []
        self.disptexts = []
        self.time = 5
        self.row = 1
        self.dispwidth = width
        self.disptext = rows
        self.pixels_width = lpixels
        self.pixels_height = kpixels
        self.screen = OLEDDISPLAY.SH1106_I2C(self.pixels_width, self.pixels_height, i2c)
        self.screentext = ""
        self.screen.poweron()
        self.screen.init_display()
        self.inverse = False

    async def long_text_to_screen(self, text, time, row=1):
        self.time = time
        self.row = row
        self.disptexts.clear()
        self.rows.clear()
        self.screentext = [text[y-self.dispwidth:y] for y in range(self.dispwidth,
                           len(text)+self.dispwidth, self.dispwidth)]
        for y in range(len(self.disptexts)):
            self.rows.append(self.disptexts[y])
        if len(self.rows) > self.disptext:
            pages = len(self.disptexts) // self.disptext
        else:
            pages = 1
        if pages == 1:
            for z in range(0, len(self.rows)):
                self.screen.text(self.rows[z], 0, self.row + z * 10, 1)

    async def text_to_row(self, text, row, time):
        self.time = time
        if len(text) > self.dispwidth:
            self.screen.text('Row too long', 0, 1 + row * 10, 1)
        elif len(text) <= self.dispwidth:
            self.screen.text(text, 0, 1 + row * 10, 1)

    async def activate_screen(self):
        self.screen.sleep(False)
        self.screen.show()
        await asyncio.sleep(self.time)
        self.screen.sleep(True)
        self.screen.init_display()

    async def contrast(self, contrast=255):
        if contrast > 1 or contrast < 255:
            self.screen.contrast(contrast)

    async def inverse_color(self, inverse=False):
        self.inverse = inverse
        self.screen.invert(inverse)

    async def rotate_180(self, rotate=False):
        self.screen.rotate(rotate)

    async def draw_frame(self):
        if self.inverse is False:
            self.screen.framebuf.rect(1, 1, self.pixels_width-1, self.pixels_height-1, 0xffff)
        else:
            self.screen.framebuf.rect(1, 1, self.pixels_width - 1, self.pixels_height - 1, 0x0000)

    async def draw_underline(self, row, width):
        rowheight = self.pixels_height / self.row
        startx = 1
        starty = 8 + (int(rowheight * row))
        charwidth = int(8 * width)
        if self.inverse is False:
            self.screen.framebuf.hline(startx, starty, charwidth, 0xffff)
        else:
            self.screen.framebuf.hline(startx, starty, charwidth, 0x0000)

    async def reset_screen(self):
        self.screen.reset()

    async def shut_screen(self):
        self.screen.poweroff()

    async def start_screen(self):
        self.screen.poweron()


async def mqtt_up_loop():
    global mqtt_up
    global client

    while net.net_ok is False:
        gc.collect()
        await asyncio.sleep(5)

    if net.net_ok is True:
        config['subs_cb'] = update_mqtt_status
        config['connect_coro'] = mqtt_subscribe
        config['ssid'] = net.use_ssid
        config['wifi_pw'] = net.u_pwd
        MQTTClient.DEBUG = True
        client = MQTTClient(config)
        try:
            await client.connect()
        except OSError as e:
            print("Soft reboot caused error %s" % e)
            await asyncio.sleep(5)
            reset()
        while mqtt_up is False:
            await asyncio.sleep(5)
            try:
                await client.connect()
                if client.isconnected() is True:
                    mqtt_up = True
            except OSError as e:
                if DEBUG_SCREEN_ACTIVE == 1:
                    print("MQTT error: %s" % e)
                    print("Config: %s" % config)
    n = 0
    while True:
        # await self.mqtt_subscribe()
        await asyncio.sleep(5)
        if DEBUG_SCREEN_ACTIVE == 1:
            print('mqtt-publish', n)
        await client.publish('result', '{}'.format(n), qos=1)
        n += 1


async def mqtt_subscribe(client):
    # If "client" is missing, you get error from line 538 in MQTT_AS.py (1 given, expected 0)
    await client.subscribe('$SYS/broker/uptime', 1)


def update_mqtt_status(topic, msg, retained):
    global broker_uptime
    if DEBUG_SCREEN_ACTIVE == 1:
        print((topic, msg, retained))
    broker_uptime = msg


async def show_what_i_do():
    # Output is REPL
    adcmq135 = ADC(Pin(MQ135_AO_PIN))

    while True:
        print("\n1 ---------WIFI------------- 1")
        if START_NETWORK == 1:
            print("   WiFi Connected %s, hotspot: %s, signal strength: %s" % (net.net_ok, net.use_ssid, net.strength))
            print("   IP-address: %s, connection attempts failed %s" % (net.ip_a, net.con_att_fail))
        if START_MQTT == 1:
            print("   MQTT Connected: %s, broker uptime: %s" % (mqtt_up, broker_uptime))
        print("   Memory free: %s, allocated: %s" % (gc.mem_free(), gc.mem_alloc()))
        print("   Heap info %s, hall sensor %s, raw-temp %sC" % (esp32.idf_heap_info(esp32.HEAP_DATA),
                                                                esp32.hall_sensor(),
                                                                "{:.1f}".format(((float(esp32.raw_temperature())-32.0)
                                                                                 * 5/9))))
        print("2 ---------SENSOR----------- 2")
        if (temp_average is not None) and (rh_average is not None):
            print("   Temp: %sC, Rh: %s" % (temp_average, rh_average))
        if not BME280_sensor_faulty:
            if bmes.values[1][:-3] is not None:
                print("   Pressure: %s" % bmes.values[1][:-3])
        if co2_average is not None:
            print("   CO2 is %s" % co2_average)
        print("3 ----------ADC------------- 3")
        if (temp_average is not None) and (rh_average is not None):
            print("   ADC value from MQ135 pin %s, corrected RZERO: %s" %
                  (adcmq135.read(), co2s.get_corrected_rzero(temp_average, rh_average)))
        print("\n")
        await asyncio.sleep(5)

# Adjust speed to low heat production, max 240000000, normal 160000000, min with Wi-Fi 80000000
#  freq(240000000)
freq(80000000)

# Network handshake
net = WIFINET.ConnectWiFi(SSID1, PASSWORD1, SSID2, PASSWORD2, NTPSERVER, DHCP_NAME, START_WEBREPL, WEBREPL_PASSWORD)

# BME280 or BMP280 sensor
i2c = SoftI2C(scl=Pin(I2C_SCL_PIN), sda=Pin(I2C_SDA_PIN))
try:
    bmes = BmESensor.BME280(i2c=i2c)
    if bmes.values[2][:-1] == '0.00':
        BME280_sensor_type = "BMP280"
except OSError as e:
    print("Error: %s - BME sensor init error!" % e)
    BME280_sensor_faulty = True
#  If BMP280 and DHT22 is used, then Rh is read from DHT22 and Temp from BMP280
#  Else if only BME280 is used, all values are read from BME280

DHTSensor = dht.DHT22(Pin(DHT_PIN))
try:
    DHTSensor.measure()
except OSError as e:
    print("Error: %s - DHT22 sensor init error!" % e)
    DHT22_sensor_faulty = True

if (DHTSensor.humidity() == 0.0) or (DHTSensor.temperature() == 0.0):
    print("Error: %s - DHT22 sensor init error!")
    DHT22_sensor_faulty = True

# MQ135 init. The loadresistor is resistor between GND and MQ135 B1 pin. Resistorzero is after calibration.
try:
    co2s = CO2SENSOR.MQ135_ao(ao_pin=Pin(MQ135_AO_PIN), loadresistor=MQ135_RESISTOR, resistorzero=MQ135_RZERO)
except OSError as e:
    print("Error: %s - MQ135 sensor init error!" % e)
    MQ135_sensor_faulty = True

#  OLED display
try:
    display = Displayme()
except OSError as e:
    print("Error: %s - OLED Display init error!" % e)

# Touch thing
touch = TouchPad(Pin(TOUCH_PIN))


async def touch_check_loop():
    press_time = time()
    while True:
        if touch.read() < 400:    # Sensitivity
            press_time = time()
        elif (touch.read() > 400) and ((time() - press_time) > SCREEN_TIMEOUT):
            await display.shut_screen()
        else:
            await display.activate_screen()
            await page_1()
            await display.activate_screen()
            await page_2()
        await asyncio.sleep_ms(10)


async def read_sensors_loop():
    global co2_average
    global temp_average
    global rh_average
    ppm_list = []
    temp_list = []
    rh_list = []
    rzero_list = []
    #  Read values from sensor once per second, add them to the array, delete oldest when size 60 (seconds)
    while True:
        try:
            # if sensor is BME280, use below line ([0] = temp, [1] = pressure, [2] = rh:
            if (BME280_sensor_type == "BME280") and (not BME280_sensor_faulty):
                temp_list.append(round(float(bmes.values[0][:-1]), 1) + TEMP_CORRECTION)
                rh_list.append(round(float(bmes.values[2][:-1]), 1) + RH_CORRECTION)
                ppm_list.append(co2s.get_corrected_ppm(round(float(bmes.values[0][:-1]), 1) + TEMP_CORRECTION,
                                                       round(float(bmes.values[2][:-1]), 1)+RH_CORRECTION) +
                                CO2_CORRECTION)
            elif (BME280_sensor_type == "BMP280") and (not BME280_sensor_faulty) and (not DHT22_sensor_faulty):
                # Rh from DHT22
                try:
                    DHTSensor.measure()
                except OSError:
                    await asyncio.sleep(1)
                    DHTSensor.measure()
                temp_list.append(round(float(bmes.values[0][:-1]), 1) + TEMP_CORRECTION)
                rh_list.append(round(float(DHTSensor.humidity()), 1) + RH_CORRECTION)
                ppm_list.append(co2s.get_corrected_ppm(round(float(bmes.values[0][:-1]), 1) + TEMP_CORRECTION,
                                                       round(float(DHTSensor.humidity()), 1)+RH_CORRECTION)+
                                CO2_CORRECTION)
            elif (BME280_sensor_faulty is True) and (not DHT22_sensor_faulty):  # Temp and Rh from DHT22
                try:
                    DHTSensor.measure()
                except OSError:
                    await asyncio.sleep(1)
                    DHTSensor.measure()
                temp_list.append(round(float(DHTSensor.temperature()), 1)+TEMP_CORRECTION)
                rh_list.append(round(float(DHTSensor.humidity()), 1)+RH_CORRECTION)
                ppm_list.append(co2s.get_corrected_ppm(round(float(DHTSensor.temperature()), 1)+TEMP_CORRECTION,
                                                       round(float(DHTSensor.humidity()), 1) +RH_CORRECTION)+
                                CO2_CORRECTION)
            else:   # Missing temperature and rh information
                ppm_list.append(co2s.get_ppm()+CO2_CORRECTION)
        except ValueError:
            pass
        #  Adjust RZERO of the MQ135 sensor based on 20 measurement average
        if (not MQ135_sensor_faulty) and (temp_average is not None) and (rh_average is not None):
            rzero_list.append(co2s.get_corrected_rzero(temp_average, rh_average))
            if len(rzero_list) >= 20:
                rzero_list.pop(0)
            elif len(rzero_list) > 1:
                 co2s.set_new_rzero(round(sum(rzero_list) / len(rzero_list), 2))
        if len(ppm_list) >= 60:
            ppm_list.pop(0)
        if len(temp_list) >= 60:
            temp_list.pop(0)
        if len(rh_list) >= 60:
            rh_list.pop(0)
        if len(ppm_list) > 1:
            co2_average = round(sum(ppm_list) / len(ppm_list), 1)
        if len(temp_list) > 1:
            temp_average = round(sum(temp_list) / len(temp_list), 1)
        if len(rh_list) > 1:
            rh_average = round(sum(rh_list) / len(rh_list), 1)
        gc.collect()
        await asyncio.sleep(1)


async def mqtt_publish_loop():
    #  Publish only valid average values.

    while True:
        if mqtt_up is False:
            await asyncio.sleep(10)
        else:
            await asyncio.sleep(MQTT_INTERVAL)
            if temp_average is not None:
                if -40 < temp_average < 100:
                    await client.publish(TOPIC_TEMP, str(temp_average), retain=0, qos=0)
                    # float to str conversion due to MQTT_AS.py len() issue
            if rh_average is not None:
                if 0 < rh_average < 100:
                    await client.publish(TOPIC_RH, str(rh_average), retain=0, qos=0)
            if not BME280_sensor_faulty:
                if bmes.values[1][:-3] is not None:
                    await client.publish(TOPIC_PRESSURE, bmes.values[1][:-3], retain=0, qos=0)
            if co2_average is not None:
                if 400 < co2_average < 8000:
                    await client.publish(TOPIC_CO2, str(co2_average), retain=0, qos=0)
# For MQTT_AS
config['server'] = MQTT_SERVER
config['user'] = MQTT_USER
config['password'] = MQTT_PASSWORD
config['port'] = MQTT_PORT
config['client_id'] = CLIENT_ID
if MQTT_USE_SSL == "True":
    config['ssl'] = True
else:
    config['ssl'] = False
client = MQTTClient(config)


#  What we show on the OLED display
async def page_1():
    await display.text_to_row("PVM:%s" % resolve_date()[0], 0, 5)
    await display.text_to_row("KLO:%s" % resolve_date()[1], 1, 5)
    if co2_average is not None:
        await display.text_to_row("%s co2 ppm" % co2_average, 2, 5)
    if temp_average is None:
        await display.text_to_row("Waiting values", 3, 5)
    else:
        await display.text_to_row("%s C" % temp_average, 3, 5)
    if rh_average is None:
        await display.text_to_row("Waiting values", 4, 5)
    else:
        await display.text_to_row("Rh: %s" % rh_average, 4, 5)
    if not BME280_sensor_faulty:
        if bmes.values[1] is not None:
            await display.text_to_row("%s ppm" % bmes.values[1], 5, 5)
    await asyncio.sleep_ms(10)


async def page_2():
    await display.text_to_row("STATUS", 0, 5)
    await display.draw_underline(0, 6)
    if START_MQTT:
        await display.text_to_row("MQTT up: %s" % mqtt_up, 1, 5)
    if net.net_ok:
        await display.text_to_row("rssi: %s" % network.WLAN(network.STA_IF).status('rssi'), 2, 5)
    await display.text_to_row("Memfree: %s" % gc.mem_free(), 3, 5)
    await display.text_to_row("Hall: %s" % esp32.hall_sensor(), 4, 5)
    await display.text_to_row("MCU C: %s" % ("{:.1f}".format(((float(esp32.raw_temperature())-32.0) * 5/9))), 5, 5)
    await asyncio.sleep_ms(10)


async def main():
    loop = asyncio.get_event_loop()
    if START_NETWORK == 1:
        loop.create_task(net.net_upd_loop())
    if DEBUG_SCREEN_ACTIVE == 1:
        loop.create_task(show_what_i_do())
    if START_MQTT == 1:
        loop.create_task(mqtt_up_loop())
        loop.create_task(mqtt_publish_loop())
    loop.create_task(read_sensors_loop())
    loop.create_task(touch_check_loop())
    loop.run_forever()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except MemoryError:
        reset()
