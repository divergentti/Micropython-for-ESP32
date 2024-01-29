"""
ESP32 with esp32-ota-20230426-v1.20.0.bin micropython.

This script is used for I2C connected OLED display, BME680 temperature/rh/pressure/voc sensor
The BME680 sensor do not have IAQ driver (Bosch BSEC) for MPY yet. You can not make proper IAQ calucalations.
Building own firmware is not possible, because only .a C driver is published from BSEC.
Temperature readings are also off. Might be wise to use some other sensor.

Enclosure to be printed with 3D printer is available from Thingsverse https://www.thingiverse.com/thing:6063412

As default, I2C for the OLED and BME680 are connected to SDA = Pin21 and SCL (SCK) = Pin22 (check parameters.py).
Use command i2c.scan() to check which devices respond from the I2C channel.

Program read sensor values once per second, rounds them to 1 decimal with correction values, then calculates averages.
Averages are sent to the MQTT broker defined in runtimeconfig.json.

For webrepl, remember to execute import webrepl_setup one time.

Asynchronous code.

Version 0.1 Jari Hiltunen - 6.6.2023 and most likely last code update due to sensor issue
Updated 20.6.2023 - removed gas resistance limits from MQTT publish. Values seems to go over 650 kOhm
Updated 29.1.2024 - shortened variable names and added error logging file size checkup
"""

from machine import SoftI2C, Pin, freq, reset
import uasyncio as asyncio
from utime import mktime, localtime
import gc
import drivers.BME680 as BSENS
import drivers.SH1106 as ODISP
gc.collect()
import drivers.WIFICONN_AS as WNET
gc.collect()
from json import load
import esp32
from drivers.MQTT_AS import MQTTClient, config
import os
gc.collect()
# Globals
mqtt_up = False
bro_uptime = 0
t_ave = 0
rh_ave = 0
press_ave = 0
gas_r_ave = 0
BME680_sensor_faulty = False


def log_errors(err_in):
    filename = "/errors.csv"
    max_file_size_bytes = 1024  # 1KB

    with open(filename, 'a+') as logf:
        try:
            logf.write("%s" % str(resolve_date()[0]))  # Date in local format
            logf.write(",")
            logf.write("%s" % str(err_in))
            logf.write("\r\n")
        except OSError:
            print("Can not write to ", filename, "!")
            raise OSError

    logf.close()

    # Check file size and shrink/delete if needed
    try:
        file_stat = os.stat(filename)
        file_size_bytes = file_stat[6]  # Index 6 corresponds to file size

        if file_size_bytes > max_file_size_bytes:
            with open(filename, 'r') as file:
                lines = file.readlines()
                lines = lines[-1000:]  # Keep the last 1000 lines
            with open(filename, 'w') as file:
                file.writelines(lines)
    except OSError as e:
        if e.args[0] == 2:  # File not found error
            # File doesn't exist, create it
            with open(filename, 'w') as file:
                pass  # Just create an empty file
        else:
            print("Error while checking/shrinking the log file.")
            raise OSError


try:
    f = open('parameters.py', "r")
    from parameters import I2C_SCL_PIN, I2C_SDA_PIN, TOUCH_PIN
    f.close()
except OSError as err:  # open failed
    log_errors("Parameters: %s" % err)
    print("parameter.py-file missing! Can not continue!")
    raise

try:
    f = open('runtimeconfig.json', 'r')
    with open('runtimeconfig.json') as config_file:
        data = load(config_file)
        f.close()
        SID1 = data['SSID1']
        SID2 = data['SSID2']
        PWD1 = data['PASSWORD1']
        PWD2 = data['PASSWORD2']
        MQTT_S = data['MQTT_SERVER']
        MQTT_P = data['MQTT_PASSWORD']
        MQTT_U = data['MQTT_USER']
        MQTT_PRT = data['MQTT_PORT']
        MQTT_SSL = data['MQTT_SSL']
        MQTT_IVAL = data['MQTT_INTERVAL']
        CLNT_ID = data['CLIENT_ID']
        TOPIC_ERR = data['TOPIC_ERRORS']
        WBRPL_PWD = data['WEBREPL_PASSWORD']
        NTPS = data['NTPSERVER']
        DHCP_N = data['DHCP_NAME']
        S_WBRPL = data['START_WEBREPL']
        S_NET = data['START_NETWORK']
        S_MQTT = data['START_MQTT']
        SCR_UPD_IVAL = data['SCREEN_UPDATE_INTERVAL']
        D_SCR_ACT = data['DEBUG_SCREEN_ACTIVE']
        SCR_TOUT = data['SCREEN_TIMEOUT']
        T_TEMP = data['TOPIC_TEMP']
        T_RH = data['TOPIC_RH']
        T_PRESS = data['TOPIC_PRESSURE']
        T_GASR = data['TOPIC_GASR']
        T_IAQ = data['TOPIC_IAQ']
        T_DP = data['TOPIC_DP']
        TEMP_THOLD = data['TEMP_TRESHOLD']
        TEMP_CORR = data['TEMP_CORRECTION']
        RH_THOLD = data['RH_TRESHOLD']
        RH_CORR = data['RH_CORRECTION']
        PRESS_THOLD = data['PRESSURE_TRESHOLD']
        PRESS_CORR = data['PRESSURE_CORRECTION']
        DST_B_M = data['DST_BEGIN_M']
        DST_B_DAY = data['DST_BEGIN_DAY']
        DST_B_OCC = data['DST_BEGIN_OCC']
        DST_B_TIME = data['DST_BEGIN_TIME']
        DST_END_M = data['DST_END_M']
        DST_END_D = data['DST_END_DAY']
        DST_END_TIME = data['DST_END_TIME']
        DST_END_OCC = data['DST_END_OCC']
        DST_TZONE = data['DST_TIMEZONE']
except OSError as er:
    log_errors("Runtime.json: %s" % er)
    print("Runtime parameters missing. Can not continue!")
    raise


def weekday(year, month, day):
    # Returns weekday. Thanks to 2DOF @ GitHub
    t = [0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4]
    year -= month < 3
    return (year + int(year / 4) - int(year / 100) + int(year / 400) + t[month - 1] + day) % 7


def resolve_dst():
    (year, month, mdate, hour, minute, second, wday, yday) = localtime()   # supposed to be GMT/UTC
    match_d_begin = []
    match_d_end = []
    # Define the DST rules for the specified time zone
    # Replace these rules with the actual DST rules for your time zone
    dst_rules = {
        "begin": (DST_B_M, DST_B_DAY, DST_B_OCC, DST_B_TIME),
        # 3 = March, 2 = last, 6 = Sunday, 3 = 03:00
        "end": (DST_END_M, DST_END_D, DST_END_OCC, DST_END_TIME),   # DST end  month, day, 1=first, 2=last at 04:00.
        # 10 = October, 2 = last, 6 = Sunday, 4 = 04:00
        "timezone": DST_TZONE,          # hours from UTC during normal (winter time)
        "offset": 1                     # hours to be added to timezone when DST is True
    }
    # Iterate begin
    if dst_rules["begin"][0] in (1, 3, 5, 7, 8, 10, 11):
        days_in_month = 30
    else:
        days_in_month = 31   # February does not matter here
    # Iterate months and find days matching criteria
    for x in range(days_in_month):
        if weekday(year, dst_rules["begin"][0], x) == dst_rules["begin"][1]:
            if dst_rules["begin"][2] == 2:  # last day first in the list
                match_d_begin.insert(0, x)
            else:
                match_d_begin.append(x)  # first day first in the list
    dst_begin = mktime((year, dst_rules["begin"][0], match_d_begin[0],
                        dst_rules["begin"][3], 0, 0, dst_rules["begin"][1], 0))
    if dst_rules["end"][0] in (1, 3, 5, 7, 8, 10, 11):
        days_in_month = 30
    else:
        days_in_month = 31   # February does not matter here
    for x in range(days_in_month):
        if weekday(year, dst_rules["end"][0], x) == dst_rules["end"][1]:
            if dst_rules["end"][2] == 2:  # last day first in the list
                match_d_end.insert(0, x)
            else:
                match_d_end.append(x)  # first day first in the list
    dst_end = mktime((year, dst_rules["end"][0], match_d_end[0], dst_rules["end"][3], 0, 0, dst_rules["end"][1], 0))
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


class Displ(object):
    """ For the OLED display init and displaying text """

    def __init__(self, width=16, rows=6, lpixels=128, kpixels=64):
        self.rows = []
        self.d_texts = []
        self.time = 5
        self.row = 1
        self.d_w = width
        self.d_text = rows
        self.pix_w = lpixels
        self.pix_h = kpixels
        self.scr = ODISP.SH1106_I2C(self.pix_w, self.pix_h, i2c)
        self.scr_txt = ""
        self.scr.poweron()
        self.scr.init_display()
        self.inverse = False

    async def l_txt_to_scr(self, text, time, row=1):
        self.time = time
        self.row = row
        self.d_texts.clear()
        self.rows.clear()
        self.scr_txt = [text[y - self.d_w:y] for y in range(self.d_w,
                                                            len(text) + self.d_w, self.d_w)]
        for y in range(len(self.d_texts)):
            self.rows.append(self.d_texts[y])
        if len(self.rows) > self.d_text:
            pages = len(self.d_texts) // self.d_text
        else:
            pages = 1
        if pages == 1:
            for z in range(0, len(self.rows)):
                self.scr.text(self.rows[z], 0, self.row + z * 10, 1)

    async def txt_to_row(self, text, row, time):
        self.time = time
        if len(text) > self.d_w:
            self.scr.text('Row too long', 0, 1 + row * 10, 1)
        elif len(text) <= self.d_w:
            self.scr.text(text, 0, 1 + row * 10, 1)

    async def act_scr(self):
        self.scr.show()
        await asyncio.sleep(self.time)
        self.scr.init_display()

    async def contrast(self, contrast=255):
        if contrast > 1 or contrast < 255:
            self.scr.contrast(contrast)

    async def inverse_color(self, inverse=False):
        self.inverse = inverse
        self.scr.invert(inverse)

    async def rot_180(self, rotate=False):
        self.scr.rotate(rotate)

    async def draw_frame(self):
        if self.inverse is False:
            self.scr.framebuf.rect(1, 1, self.pix_w - 1, self.pix_h - 1, 0xffff)
        else:
            self.scr.framebuf.rect(1, 1, self.pix_w - 1, self.pix_h - 1, 0x0000)

    async def draw_underline(self, row, width):
        r_h = self.pix_h / self.row
        x = 1
        y = 8 + (int(r_h * row))
        c_w = int(8 * width)
        if self.inverse is False:
            self.scr.framebuf.hline(x, y, c_w, 0xffff)
        else:
            self.scr.framebuf.hline(x, y, c_w, 0x0000)

    async def reset_scr(self):
        self.scr.reset()

    async def shut_scr(self):
        self.scr.poweroff()

    async def start_scr(self):
        self.scr.poweron()


async def mqtt_up_loop():
    global mqtt_up
    global client

    while net.net_ok is False:
        gc.collect()
        await asyncio.sleep(5)

    if net.net_ok is True:
        config['subs_cb'] = upd_mqtt_stat
        config['connect_coro'] = mqtt_subs
        config['ssid'] = net.use_ssid
        config['wifi_pw'] = net.u_pwd
        MQTTClient.DEBUG = True
        client = MQTTClient(config)
        try:
            await client.connect()
        except OSError as e:
            log_errors("WiFi connect: %s" % e)
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
                log_errors("MQTT Connect: %s" % e)
                if D_SCR_ACT == 1:
                    print("MQTT error: %s" % e)
                    print("Config: %s" % config)
    n = 0
    while True:
        # await self.mqtt_subscribe()
        await asyncio.sleep(5)
        if D_SCR_ACT == 1:
            print('mqtt-publish', n)
        await client.publish('result', '{}'.format(n), qos=1)
        n += 1


async def mqtt_subs(client):
    # If "client" is missing, you get error from line 538 in MQTT_AS.py (1 given, expected 0)
    await client.subscribe('$SYS/broker/uptime', 1)


def upd_mqtt_stat(topic, msg, retained):
    global bro_uptime
    if D_SCR_ACT == 1:
        print((topic, msg, retained))
    bro_uptime = msg


async def s_what_i_do():
    # Output is REPL

    while True:
        print("\n1 ---------WIFI------------- 1")
        if S_NET == 1:
            print("   WiFi Connected %s, hotspot: hidden, signal strength: %s" % (net.net_ok,  net.strength))
            print("   IP-address: %s" % net.ip_a)
        if S_MQTT == 1:
            print("   MQTT Connected: %s, broker uptime: %s" % (mqtt_up, bro_uptime))
        print("   Memory free: %s, allocated: %s" % (gc.mem_free(), gc.mem_alloc()))
        print("   Heap info %s, hall sensor %s, raw-temp %sC" % (esp32.idf_heap_info(esp32.HEAP_DATA),
                                                                 esp32.hall_sensor(),
                                                                 "{:.1f}".format(
                                                                     ((float(esp32.raw_temperature()) - 32.0)
                                                                      * 5 / 9))))
        print("2 ---------SENSOR----------- 2")
        if not BME680_sensor_faulty:
            if (t_ave is not None) and (rh_ave is not None):
                print("   Temp: %sC, Rh: %s" % (t_ave, rh_ave))
            if gas_r_ave is not None:
                print("   GasR: %s" % (gas_r_ave / 1000))  # kOhms
            if press_ave is not None:
                print("   Pressure: %s" % press_ave)
        print("\n")
        await asyncio.sleep(5)


# Adjust speed to low heat production, max 240000000, normal 160000000, min with Wi-Fi 80000000
#  freq(240000000)
freq(80000000)

# Network handshake
net = WNET.ConnectWiFi(SID1, PWD1, SID2, PWD2, NTPS, DHCP_N, S_WBRPL, WBRPL_PWD)

i2c = SoftI2C(scl=Pin(I2C_SCL_PIN), sda=Pin(I2C_SDA_PIN))
try:
    bmes = BSENS.BME680_I2C(i2c=i2c)
except OSError as e:
    log_errors("BMES init: %s" % e)
    raise Exception("Error: %s - BME sensor init error!" % e)

#  OLED display
try:
    display = Displ()
except OSError as e:
    log_errors("OLED init: %s" % e)
    raise Exception("Error: %s - OLED Display init error!" % e)


async def read_sens_loop():
    global t_ave
    global rh_ave
    global press_ave
    global gas_r_ave
    temp_list = []
    rh_list = []
    press_list = []
    gas_r_list = []
    #  Read values from sensor once per second, add them to the array, delete oldest when size 60 (seconds)
    while True:
        try:
            temp_list.append((float(bmes.temperature)) + TEMP_CORR)
            rh_list.append((float(bmes.humidity)) + RH_CORR)
            press_list.append((float(bmes.pressure)) + PRESS_CORR)
            gas_r_list.append((float(bmes.gas)))
        except ValueError as e:
            log_errors("Value error in BME loop: %s" % e)
        else:
            if len(temp_list) >= 60:
                temp_list.pop(0)
            if len(rh_list) >= 60:
                rh_list.pop(0)
            if len(press_list) >= 60:
                press_list.pop(0)
            if len(gas_r_list) >= 60:
                gas_r_list.pop(0)
            if len(temp_list) > 1:
                t_ave = round(sum(temp_list) / len(temp_list), 1)
            if len(rh_list) > 1:
                rh_ave = round(sum(rh_list) / len(rh_list), 1)
            if len(press_list) > 1:
                press_ave = round(sum(press_list) / len(press_list), 1)
            if len(gas_r_list) > 1:
                gas_r_ave = round(sum(gas_r_list) / len(gas_r_list), 1)
            gc.collect()
            await asyncio.sleep(1)


async def mqtt_pub_loop():
    #  Publish only valid average values.

    while True:
        if mqtt_up is False:
            await asyncio.sleep(10)
        else:
            await asyncio.sleep(MQTT_IVAL)
            if -40 < t_ave < 100:
                await client.publish(T_TEMP, str(t_ave), retain=0, qos=0)
                # float to str conversion due to MQTT_AS.py len() issue
            if 0 < rh_ave < 100:
                await client.publish(T_RH, str(rh_ave), retain=0, qos=0)
            if 0 < press_ave < 5000:
                await client.publish(T_PRESS, str(press_ave), retain=0, qos=0)
            await client.publish(T_GASR, str(gas_r_ave), retain=0, qos=0)


# For MQTT_AS
config['server'] = MQTT_S
config['user'] = MQTT_U
config['password'] = MQTT_P
config['port'] = MQTT_PRT
config['client_id'] = CLNT_ID
if MQTT_SSL == "True":
    config['ssl'] = True
else:
    config['ssl'] = False
client = MQTTClient(config)


async def disp_loop():
    while True:
        await display.rot_180(True)
        await display.txt_to_row("  %s %s" % (resolve_date()[2], resolve_date()[0]), 0, 5)
        await display.txt_to_row("    %s" % resolve_date()[1], 1, 5)
        await display.txt_to_row("%sC Rh %s %%" % (t_ave, rh_ave), 2, 5)
        await display.txt_to_row("Pressure:%s" % press_ave, 3, 5)
        await display.txt_to_row("GasRes:%s" % gas_r_ave, 4, 5)
        await display.txt_to_row("MCU Temp:%s " % (("{:.1f}".format((
                (float(esp32.raw_temperature()) - 32.0) * 5 / 9)))), 5, 5)
        await display.act_scr()
        await asyncio.sleep(1)


async def main():
    loop = asyncio.get_event_loop()
    if S_NET == 1:
        loop.create_task(net.net_upd_loop())
    if D_SCR_ACT == 1:
        loop.create_task(s_what_i_do())
    if S_MQTT == 1:
        loop.create_task(mqtt_up_loop())
        loop.create_task(mqtt_pub_loop())
    loop.create_task(read_sens_loop())
    loop.create_task(disp_loop())
    loop.run_forever()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except MemoryError as e:
        log_errors(e)
        reset()
