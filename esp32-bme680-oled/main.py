"""
ESP32 with esp32-ota-20230426-v1.20.0.bin micropython.

This script is used for I2C connected OLED display, BME680 temperature/rh/pressure/voc sensor

As default, I2C for the OLED and BME680 are connected to SDA = Pin21 and SCL (SCK) = Pin22 (check parameters.py).
Use command i2c.scan() to check which devices respond from the I2C channel.

Program read sensor values once per second, rounds them to 1 decimal with correction values, then calculates averages.
Averages are sent to the MQTT broker defined in runtimeconfig.json.

For webrepl, remember to execute import webrepl_setup one time.

Asyncronous code.

Version 0.1 Jari Hiltunen -  xxxxxx
"""


from machine import SoftI2C, Pin, freq, reset
import uasyncio as asyncio
from utime import mktime, localtime, sleep
import gc
import drivers.WIFICONN_AS as WIFINET
import drivers.BME680 as BmESensor
import drivers.SH1106 as OLEDDISPLAY

gc.collect()
from json import load
import esp32
from drivers.MQTT_AS import MQTTClient, config
gc.collect()
# Globals
mqtt_up = False
broker_uptime = 0
temp_average = 0
rh_average = 0
pressure_average = 0
gas_r_average = 0
iaq = 0
BME680_sensor_faulty = False


try:
    f = open('parameters.py', "r")
    from parameters import I2C_SCL_PIN, I2C_SDA_PIN, TOUCH_PIN
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
        TOPIC_TEMP = data['TOPIC_TEMP']
        TOPIC_RH = data['TOPIC_RH']
        TOPIC_PRESSURE = data['TOPIC_PRESSURE']
        TOPIC_GASR = data['TOPIC_GASR']
        TOPIC_IAQ = data['TOPIC_IAQ']
        TOPIC_DP = data['TOPIC_DP']
        TEMP_THOLD = data['TEMP_TRESHOLD']
        TEMP_CORRECTION = data['TEMP_CORRECTION']
        RH_THOLD = data['RH_TRESHOLD']
        RH_CORRECTION = data['RH_CORRECTION']
        P_THOLD = data['PRESSURE_TRESHOLD']
        PRESSURE_CORRECTION = data['PRESSURE_CORRECTION']
        DST_BEGIN_M =data['DST_BEGIN_M']
        DST_BEGIN_DAY= data['DST_BEGIN_DAY']
        DST_BEGIN_OCC = data['DST_BEGIN_OCC']
        DST_BEGIN_TIME = data['DST_BEGIN_TIME']
        DST_END_M = data['DST_END_M']
        DST_END_DAY = data['DST_END_DAY']
        DST_END_TIME = data['DST_END_TIME']
        DST_END_OCC = data['DST_END_OCC']
        DST_TIMEZONE = data['DST_TIMEZONE']
except OSError:
    print("Runtime parameters missing. Can not continue!")
    sleep(30)
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

    while True:
        print("\n1 ---------WIFI------------- 1")
        if START_NETWORK == 1: #net.use_ssid,
            print("   WiFi Connected %s, hotspot: hidden, signal strength: %s" % (net.net_ok,  net.strength))
            # print("   IP-address: %s, connection attempts failed %s" % (net.ip_a, net.con_att_fail))
        # if START_MQTT == 1:
            # print("   MQTT Connected: %s, broker uptime: %s" % (mqtt_up, broker_uptime))
        print("   Memory free: %s, allocated: %s" % (gc.mem_free(), gc.mem_alloc()))
        print("   Heap info %s, hall sensor %s, raw-temp %sC" % (esp32.idf_heap_info(esp32.HEAP_DATA),
                                                                 esp32.hall_sensor(),
                                                                 "{:.1f}".format(
                                                                     ((float(esp32.raw_temperature()) - 32.0)
                                                                      * 5 / 9))))
        print("2 ---------SENSOR----------- 2")
        if not BME680_sensor_faulty:
            if (temp_average is not None) and (rh_average is not None):
                print("   Temp: %sC, Rh: %s" % (temp_average, rh_average))
            if gas_r_average is not None:
                print("   GasR: %s" % gas_r_average)
            if pressure_average is not None:
                print("   Pressure: %s" % pressure_average)
        print("\n")
        await asyncio.sleep(5)


# Adjust speed to low heat production, max 240000000, normal 160000000, min with Wi-Fi 80000000
#  freq(240000000)
freq(80000000)

# Network handshake
net = WIFINET.ConnectWiFi(SSID1, PASSWORD1, SSID2, PASSWORD2, NTPSERVER, DHCP_NAME, START_WEBREPL, WEBREPL_PASSWORD)

i2c = SoftI2C(scl=Pin(I2C_SCL_PIN), sda=Pin(I2C_SDA_PIN))
try:
    bmes = BmESensor.BME680_I2C(i2c=i2c)
except OSError as e:
    raise Exception("Error: %s - BME sensor init error!" % e)

#  OLED display
try:
    display = Displayme()
except OSError as e:
    raise Exception("Error: %s - OLED Display init error!" % e)


async def read_bme680_loop():
    global temp_average
    global rh_average
    global pressure_average
    global gas_r_average
    global iaq
    temp_list = []
    rh_list = []
    press_list = []
    gas_r_list = []
    #  Read values from sensor once per second, add them to the array, delete oldest when size 60 (seconds)
    while True:
        try:
            temp_list.append(round(float(bmes.temperature)) + TEMP_CORRECTION)
            rh_list.append(round(float(bmes.humidity)) + RH_CORRECTION)
            press_list.append(round(float(bmes.pressure)) + PRESSURE_CORRECTION)
            gas_r_list.append(round(float(bmes.gas)))

        except ValueError:
            pass
        if len(temp_list) >= 60:
            temp_list.pop(0)
        if len(rh_list) >= 60:
            rh_list.pop(0)
        if len(press_list) >= 60:
            press_list.pop(0)
        if len(gas_r_list) >= 60:
            gas_r_list.pop(0)
        if len(temp_list) > 1:
            temp_average = round(sum(temp_list) / len(temp_list), 1)
        if len(rh_list) > 1:
            rh_average = round(sum(rh_list) / len(rh_list), 1)
        if len(press_list) > 1:
            pressure_average = round(sum(press_list) / len(press_list), 1)
        if len(gas_r_list) > 1:
            gas_r_average = round(sum(gas_r_list) / len(gas_r_list), 1)
        gc.collect()
        await asyncio.sleep(1)


async def mqtt_publish_loop():
    #  Publish only valid average values.

    while True:
        if mqtt_up is False:
            await asyncio.sleep(10)
        else:
            await asyncio.sleep(MQTT_INTERVAL)
            if -40 < temp_average < 100:
                await client.publish(TOPIC_TEMP, str(temp_average), retain=0, qos=0)
                # float to str conversion due to MQTT_AS.py len() issue
            if 0 < rh_average < 100:
                await client.publish(TOPIC_RH, str(rh_average), retain=0, qos=0)
            if 0 < pressure_average < 5000:
                await client.publish(TOPIC_PRESSURE, str(pressure_average), retain=0, qos=0)
            if 0 < gas_r_average < 100000:
                await client.publish(TOPIC_GASR, str(gas_r_average), retain=0, qos=0)


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
        await display.text_to_row("%sC Rh %s %%" % (temp_average, rh_average), 2, 5)
        await display.text_to_row("Pressure:%s" % pressure_average, 3, 5)
        await display.text_to_row("GasRes:%s" % gas_r_average, 4, 5)
        await display.text_to_row("IAQ:%s " % iaq, 5, 5)
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
    loop.create_task(read_bme680_loop())
    loop.create_task(display_loop())
    loop.run_forever()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except MemoryError:
        reset()
