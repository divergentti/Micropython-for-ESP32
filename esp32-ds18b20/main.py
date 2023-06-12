"""
ESP32 with esp32-ota-20230426-v1.20.0.bin micropython.

This script is used for I2C connected OLED display and 5 x 1-wire DS18B20 temperature sensors.
Waterproof DS sensor with wires: black = GND, red = VDD, yellow = DATA
Parasitic mode: 1) connect DS18B20 GND (black) and VDD (red) to ESP32 GND
                2) connect DS18B20 DATA (yellow) to VDD via pullup 4.7 KOhm resistor
                3) connect DS18B20 DATA (yellow) to ESP32 GPIO (Pin4)
Use this- > conventional mode: connect DS18B20 red to ESP32 VDD (3.3V). Keep the pullup 4.7 K resistor.

Sensor addresses must be converted to base64 format to runtimeconfig.json! Use sub def find_sensors() !!

Englosure for 3D printer is available from Thingsverse.

As default, I2C for the OLED is connected to SDA = Pin21 and SCL (SCK) = Pin22 (check parameters.py).
Use command i2c.scan() to check which devices respond from the I2C channel.

Program read sensor values once per second, rounds them to 1 decimal with correction values, then calculates averages.
Averages are sent to the MQTT broker defined in runtimeconfig.json.

For webrepl, remember to execute import webrepl_setup one time.

Asyncronous code.

Version 0.1 Jari Hiltunen -126.6.2023
"""


from machine import SoftI2C, Pin, freq, reset
import ujson
import ubinascii
import onewire, ds18x20
import uasyncio as asyncio
from utime import mktime, localtime
import gc
import drivers.SH1106 as OLEDDISPLAY
gc.collect()
import drivers.WIFICONN_AS as WIFINET
gc.collect()
from json import load
import esp32
from drivers.MQTT_AS import MQTTClient, config
gc.collect()
# Globals
mqtt_up = False
broker_uptime = 0
temps1_average = 0
temps2_average = 0
temps3_average = 0
temps4_average = 0
temps5_average = 0


def log_errors(errin):
    filename = "/errors.csv"
    with open(filename, 'a+') as logf:
        try:
            logf.write("%s" % str(resolve_date()[0]))  # Date in local format
            logf.write(",")
            logf.write("%s" % str(errin))
            logf.write("\r\n")
        except OSError as e:
            print('OSError %s' % e)
            raise OSError
    logf.close()


try:
    f = open('parameters.py', "r")
    from parameters import I2C_SCL_PIN, I2C_SDA_PIN, DS_PIN
    f.close()
except OSError as e:  # open failed
    log_errors("Parameters: %s" %e)
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
        S1_ADDRESS = data['S1_ADDRESS']
        S2_ADDRESS = data['S2_ADDRESS']
        S3_ADDRESS = data['S3_ADDRESS']
        S4_ADDRESS = data['S4_ADDRESS']
        S5_ADDRESS = data['S5_ADDRESS']
        TOPIC_TEMPS1 = data['TOPIC_TEMPS1']
        TOPIC_TEMPS2 = data['TOPIC_TEMPS2']
        TOPIC_TEMPS3 = data['TOPIC_TEMPS3']
        TOPIC_TEMPS4 = data['TOPIC_TEMPS4']
        TOPIC_TEMPS5 = data['TOPIC_TEMPS5']
        TEMPS1_TRESHOLD = data['TEMPS1_TRESHOLD']
        TEMPS1_CORRECTION = data['TEMPS1_CORRECTION']
        TEMPS2_TRESHOLD = data['TEMPS2_TRESHOLD']
        TEMPS2_CORRECTION = data['TEMPS2_CORRECTION']
        TEMPS3_TRESHOLD = data['TEMPS3_TRESHOLD']
        TEMPS3_CORRECTION = data['TEMPS3_CORRECTION']
        TEMPS4_TRESHOLD = data['TEMPS4_TRESHOLD']
        TEMPS4_CORRECTION = data['TEMPS4_CORRECTION']
        TEMPS5_TRESHOLD = data['TEMPS5_TRESHOLD']
        TEMPS5_CORRECTION = data['TEMPS5_CORRECTION']
        DST_BEGIN_M =data['DST_BEGIN_M']
        DST_BEGIN_DAY= data['DST_BEGIN_DAY']
        DST_BEGIN_OCC = data['DST_BEGIN_OCC']
        DST_BEGIN_TIME = data['DST_BEGIN_TIME']
        DST_END_M = data['DST_END_M']
        DST_END_DAY = data['DST_END_DAY']
        DST_END_TIME = data['DST_END_TIME']
        DST_END_OCC = data['DST_END_OCC']
        DST_TIMEZONE = data['DST_TIMEZONE']
except OSError as e:
    log_errors("Runtime.json: %s" %e)
    print("Runtime parameters missing. Can not continue!")
    raise

def weekday(year, month, day):
    # Returns weekday. Thanks to 2DOF @ Github
    t = [0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4]
    year -= month < 3
    return (year + int(year / 4) - int(year / 100) + int(year / 400) + t[month - 1] + day) % 7

def resolve_dst():
    (year, month, mdate, hour, minute, second, wday, yday) = localtime()   # supposed to be GMT/UTC
    match_days_begin = []
    match_days_end = []
    # Define the DST rules for the specified time zone
    # Replace these rules with the actual DST rules for your time zone
    dst_rules = {
        "begin": (DST_BEGIN_M, DST_BEGIN_DAY, DST_BEGIN_OCC, DST_BEGIN_TIME),
            # 3 = March, 2 = last, 6 = Sunday, 3 = 03:00
        "end": (DST_END_M, DST_END_DAY, DST_END_OCC, DST_END_TIME),   # DST end  month, day, 1=first, 2=last at 04:00.
            # 10 = October, 2 = last, 6 = Sunday, 4 = 04:00
        "timezone": DST_TIMEZONE,          # hours from UTC during normal (winter time)
        "offset": 1                        # hours to be added to timezone when DST is True
    }
    # Iterate begin
    if dst_rules["begin"][0] in (1,3,5,7,8,10,11):
        days_in_month = 30
    else:
        days_in_month = 31   # February does not matter here
    # Iterate months and find days matching criteria
    for x in range(days_in_month):
        if weekday(year,dst_rules["begin"][0],x) == dst_rules["begin"][1]:
            if dst_rules["begin"][2] == 2:  # last day first in the list
                match_days_begin.insert(0,x)
            else:
                match_days_begin.append(x)  # first day first in the list
    dst_begin = mktime((year, dst_rules["begin"][0], match_days_begin[0], dst_rules["begin"][3], 0, 0,
                        dst_rules["begin"][1], 0))
    if dst_rules["end"][0] in (1,3,5,7,8,10,11):
        days_in_month = 30
    else:
        days_in_month = 31   # February does not matter here
    for x in range(days_in_month):
        if weekday(year,dst_rules["end"][0],x) == dst_rules["end"][1]:
            if dst_rules["end"][2] == 2:  # last day first in the list
                match_days_end.insert(0,x)
            else:
                match_days_end.append(x)  # first day first in the list
    dst_end = mktime((year, dst_rules["end"][0], match_days_end[0], dst_rules["end"][3], 0, 0,
                        dst_rules["end"][1], 0))
    if (mktime(localtime()) < dst_begin) or (mktime(localtime()) > dst_end):
        return localtime(mktime(localtime()) + 3600 * dst_rules["timezone"])
    else:
        return localtime(mktime(localtime()) + (3600 * dst_rules["timezone"]) + (3600 * dst_rules["offset"]))

def resolve_date():
    (year, month, mdate, hour, minute, second, wday, yday) = resolve_dst()
    weekdays = ['Ma', 'Ti', 'Ke', 'To', 'Pe', 'La', 'Su']
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
        self.screen.show()
        await asyncio.sleep(self.time)
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
            log_errors("WiFi connect: %s" %e)
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
                log_errors("MQTT Connect: %s" %e)
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

    while True:
        print("\n1 ---------WIFI------------- 1")
        if START_NETWORK == 1: #net.use_ssid,
            print("   WiFi Connected %s, signal strength: %s" % (net.net_ok,  net.strength))
            print("   IP-address: %s" % net.ip_a)
        if START_MQTT == 1:
            print("   MQTT Connected: %s, broker uptime: %s" % (mqtt_up, broker_uptime))
        print("   Memory free: %s, allocated: %s" % (gc.mem_free(), gc.mem_alloc()))
        print("   Heap info %s, hall sensor %s, raw-temp %sC" % (esp32.idf_heap_info(esp32.HEAP_DATA),
                                                                 esp32.hall_sensor(),
                                                                 "{:.1f}".format(
                                                                     ((float(esp32.raw_temperature()) - 32.0)
                                                                      * 5 / 9))))
        print("2 ---------SENSORS----------- 2")
        print("   Sensor 1: %s " % temps1_average)
        print("   Sensor 2: %s " % temps2_average)
        print("   Sensor 3: %s " % temps3_average)
        print("   Sensor 4: %s " % temps4_average)
        print("   Sensor 5: %s " % temps5_average)
        print("\n")
        await asyncio.sleep(5)


# Adjust speed to low heat production, max 240000000, normal 160000000, min with Wi-Fi 80000000
#  freq(240000000)
freq(80000000)

# Decode to base64
S1_ADDRESS = ubinascii.a2b_base64(S1_ADDRESS)
S2_ADDRESS = ubinascii.a2b_base64(S2_ADDRESS)
S3_ADDRESS = ubinascii.a2b_base64(S3_ADDRESS)
S4_ADDRESS = ubinascii.a2b_base64(S4_ADDRESS)
S5_ADDRESS = ubinascii.a2b_base64(S5_ADDRESS)

# DS18B20 pin. Each sensor has unique ID, so you can use just one pin. This is for 5 sensors.
ds_roms = ds18x20.DS18X20(onewire.OneWire(Pin(DS_PIN)))
found_roms = ds_roms.scan()
if len(found_roms) < 5:
    log_errors("Error: should have 5 sensors, found %s" % len(found_roms))
    raise Exception("Error: should have 5 sensors, found %s" % len(found_roms))
# Match sensor addresses to runtimejson addresses
if not S1_ADDRESS and S2_ADDRESS and S3_ADDRESS and S4_ADDRESS and S5_ADDRESS in found_roms:
    log_errors("Sensor addresses do not match to found sensors! %s" % found_roms)
    raise Exception("Sensor addresses do not match to found sensors! %s" % found_roms)


# Network handshake
net = WIFINET.ConnectWiFi(SSID1, PASSWORD1, SSID2, PASSWORD2, NTPSERVER, DHCP_NAME, START_WEBREPL, WEBREPL_PASSWORD)
i2c = SoftI2C(scl=Pin(I2C_SCL_PIN), sda=Pin(I2C_SDA_PIN))

#  OLED display
try:
    display = Displayme()
except OSError as e:
    log_errors("OLED init: %s" %e)
    raise Exception("Error: %s - OLED Display init error!" % e)


def find_sensors():
    # Shows connected sensors addresses and converts them to base64 for runtimeconfig.json
    ds_found = ds_roms.scan()
    for ds in ds_found:
        ds_roms.convert_temp()
        print("Found sensors are: %s" % ds)
        print("Encoded base64 addresses for runtimeconfig: %s" % ubinascii.b2a_base64(ds).decode('utf-8').strip())
        print("Temperature readings: %s" % ds_roms.read_temp(ds))

async def read_sensors_loop():
    global temps1_average, temps2_average, temps3_average, temps4_average, temps5_average
    temps1_list = []
    temps2_list = []
    temps3_list = []
    temps4_list = []
    temps5_list = []

    #  Read values from sensor once per second, add them to the array, delete oldest when size 60 (seconds)
    while True:
        try:
            ds_roms.convert_temp()
            temps1_list.append(ds_roms.read_temp(S1_ADDRESS) + TEMPS1_CORRECTION)
            temps2_list.append(ds_roms.read_temp(S2_ADDRESS) + TEMPS2_CORRECTION)
            temps3_list.append(ds_roms.read_temp(S3_ADDRESS) + TEMPS3_CORRECTION)
            temps4_list.append(ds_roms.read_temp(S4_ADDRESS) + TEMPS4_CORRECTION)
            temps5_list.append(ds_roms.read_temp(S5_ADDRESS) + TEMPS5_CORRECTION)
        except ValueError as e:
            log_errors("Value error in read_sensors_loop: %s" % e)
        if len(temps1_list) >= 60:
            temps1_list.pop(0)
        if len(temps2_list) >= 60:
            temps2_list.pop(0)
        if len(temps3_list) >= 60:
            temps3_list.pop(0)
        if len(temps4_list) >= 60:
            temps4_list.pop(0)
        if len(temps5_list) >= 60:
            temps5_list.pop(0)
        if len(temps1_list) > 1:
            temps1_average = round(sum(temps1_list) / len(temps1_list), 1)
        if len(temps2_list) > 1:
            temps2_average = round(sum(temps2_list) / len(temps2_list), 1)
        if len(temps3_list) > 1:
            temps3_average = round(sum(temps3_list) / len(temps3_list), 1)
        if len(temps4_list) > 1:
            temps4_average = round(sum(temps4_list) / len(temps4_list), 1)
        if len(temps5_list) > 1:
            temps5_average = round(sum(temps5_list) / len(temps5_list), 1)
        gc.collect()
        await asyncio.sleep(1)


async def mqtt_publish_loop():
    #  Publish only valid average values.

    while True:
        if mqtt_up is False:
            await asyncio.sleep(10)
        else:
            await asyncio.sleep(MQTT_INTERVAL)
            if -40 < temps1_average < 120:
                await client.publish(TOPIC_TEMPS1, str(temps1_average), retain=0, qos=0)
            if -40 < temps2_average < 120:
                await client.publish(TOPIC_TEMPS2, str(temps2_average), retain=0, qos=0)
            if -40 < temps3_average < 120:
                await client.publish(TOPIC_TEMPS3, str(temps3_average), retain=0, qos=0)
            if -40 < temps4_average < 120:
                await client.publish(TOPIC_TEMPS4, str(temps4_average), retain=0, qos=0)
            if -40 < temps5_average < 120:
                await client.publish(TOPIC_TEMPS5, str(temps5_average), retain=0, qos=0)


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
async def display_loop():
    while True:
        await display.rotate_180(True)
        await display.text_to_row("  %s %s" % (resolve_date()[2], resolve_date()[0]), 0, 5)
        await display.text_to_row("    %s" % resolve_date()[1], 1, 5)
        await display.text_to_row("In:%s Out: %s" % (temps2_average, temps1_average), 2, 5)
        await display.text_to_row("UWater:%s" % temps3_average, 3, 5)
        await display.text_to_row("HWOut:%s HWin:%s" % (temps3_average, temps5_average), 4, 5)
        # await display.text_to_row("Alarms:%s " % alarms, 5, 5)
        await display.activate_screen()
        await asyncio.sleep(1)


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
    loop.create_task(display_loop())
    loop.run_forever()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except MemoryError as e:
        log_errors(e)
        reset()
