"""
ESP32 with esp32-ota-20230426-v1.20.0.bin micropython.

This script is used for I2C connected OLED display and 5 x 1-wire DS18B20 temperature sensors.
Waterproof DS sensor with wires: black = GND, red = VDD, yellow = DATA
Parasitic mode: 1) connect DS18B20 GND (black) and VDD (red) to ESP32 GND
                2) connect DS18B20 DATA (yellow) to VDD via pull-up 4.7 KOhm resistor
                3) connect DS18B20 DATA (yellow) to ESP32 GPIO (Pin4)
Use this- > conventional mode: connect DS18B20 red to ESP32 VDD (3.3V). Keep the pull-up 4.7 K resistor.

Sensor addresses must be converted to base64 format to runtimeconfig.json! Use sub def find_sensors() !!

Enclosure for 3D printer is available from thingsverse.com

As default, I2C for the OLED is connected to SDA = Pin21 and SCL (SCK) = Pin22 (check parameters.py).
Use command i2c.scan() to check which devices respond from the I2C channel.

Program read sensor values once per second, rounds them to 1 decimal with correction values, then calculates averages.
Averages are sent to the MQTT broker defined in runtimeconfig.json.

For webrepl, remember to execute import webrepl_setup one time.

Asynchronous code.

Version 0.1 Jari Hiltunen -13.6.2023
Version 0.2 - error handling, variable names / try, except, else fix - 25.01.2024
"""


from machine import SoftI2C, Pin, freq, reset
import ubinascii
import onewire
import ds18x20
import uasyncio as asyncio
from utime import mktime, localtime
import gc
import drivers.SH1106 as DISP
gc.collect()
import drivers.WIFICONN_AS as WNET
gc.collect()
from json import load
import esp32
from drivers.MQTT_AS import MQTTClient, config
gc.collect()
import os

mqtt_up = False
bro_upt = 0
temp_s1_av = 0
temp_s2_av = 0
temp_s3_av = 0
temp_s4_av = 0
temp_s5_av = 0


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
    from parameters import I2C_SCL_PIN, I2C_SDA_PIN, DS_PIN
    f.close()
except OSError as err:  # open failed
    log_errors("Parameters: %s" % err)
    print("Error with parameters.py: ", err)
    raise OSError

try:
    f = open('runtimeconfig.json', 'r')
    with open('runtimeconfig.json') as config_file:
        data = load(config_file)
        f.close()
        sid1 = data['SSID1']
        sid2 = data['SSID2']
        pwd1 = data['PASSWORD1']
        pwd2 = data['PASSWORD2']
        mqtt_s = data['MQTT_SERVER']
        mqtt_pwd = data['MQTT_PASSWORD']
        mqtt_usr = data['MQTT_USER']
        mqtt_prt = data['MQTT_PORT']
        mqtt_use_ssl = data['MQTT_SSL']
        mqtt_ival = data['MQTT_INTERVAL']
        client_id = data['CLIENT_ID']
        t_errs = data['TOPIC_ERRORS']
        wbrpl_pwd = data['WEBREPL_PASSWORD']
        ntp_s = data['NTPSERVER']
        dhcp_n = data['DHCP_NAME']
        s_wbrpl = data['START_WEBREPL']
        s_net = data['START_NETWORK']
        s_mqtt = data['START_MQTT']
        s_upd_ival = data['SCREEN_UPDATE_INTERVAL']
        d_scr_act = data['DEBUG_SCREEN_ACTIVE']
        s_tout = data['SCREEN_TIMEOUT']
        s1_addr = data['S1_ADDRESS']
        s2_addr = data['S2_ADDRESS']
        s3_addr = data['S3_ADDRESS']
        s4_addr = data['S4_ADDRESS']
        s5_addr = data['S5_ADDRESS']
        t_temp_s1 = data['TOPIC_TEMPS1']
        t_temp_s2 = data['TOPIC_TEMPS2']
        t_temp_s3 = data['TOPIC_TEMPS3']
        t_temp_s4 = data['TOPIC_TEMPS4']
        t_temp_s5 = data['TOPIC_TEMPS5']
        temp_s1_thold = data['TEMPS1_TRESHOLD']
        temp_s1_corr = data['TEMPS1_CORRECTION']
        temp_s2_thold = data['TEMPS2_TRESHOLD']
        temp_s2_corr = data['TEMPS2_CORRECTION']
        temp_s3_thold = data['TEMPS3_TRESHOLD']
        temp_s3_corr = data['TEMPS3_CORRECTION']
        temp_s4_thold = data['TEMPS4_TRESHOLD']
        temp_s4_corr = data['TEMPS4_CORRECTION']
        temp_s5_thold = data['TEMPS5_TRESHOLD']
        temp_s5_corr = data['TEMPS5_CORRECTION']
        dst_b_M = data['DST_BEGIN_M']
        dst_b_D = data['DST_BEGIN_DAY']
        dst_b_OCC = data['DST_BEGIN_OCC']
        dst_b_time = data['DST_BEGIN_TIME']
        dst_e_M = data['DST_END_M']
        dst_e_D = data['DST_END_DAY']
        dst_e_time = data['DST_END_TIME']
        dst_e_OCC = data['DST_END_OCC']
        dst_tzone = data['DST_TIMEZONE']
except OSError as err:
    log_errors("Runtime.json: %s" % err)
    print("Error with runtime.json: ", err)
    raise OSError


def weekday(year, month, day):
    # Returns weekday. Thanks to 2DOF @ GitHub
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
        "begin": (dst_b_M, dst_b_D, dst_b_OCC, dst_b_time),
        # 3 = March, 2 = last, 6 = Sunday, 3 = 03:00
        "end": (dst_e_M, dst_e_D, dst_e_OCC, dst_e_time),   # DST end  month, day, 1=first, 2=last at 04:00.
        # 10 = October, 2 = last, 6 = Sunday, 4 = 04:00
        "timezone": dst_tzone,          # hours from UTC during normal (winter time)
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
                match_days_begin.insert(0, x)
            else:
                match_days_begin.append(x)  # first day first in the list
    dst_begin = mktime((year, dst_rules["begin"][0], match_days_begin[0], dst_rules["begin"][3], 0, 0,
                        dst_rules["begin"][1], 0))
    if dst_rules["end"][0] in (1, 3, 5, 7, 8, 10, 11):
        days_in_month = 30
    else:
        days_in_month = 31   # February does not matter here
    for x in range(days_in_month):
        if weekday(year, dst_rules["end"][0], x) == dst_rules["end"][1]:
            if dst_rules["end"][2] == 2:  # last day first in the list
                match_days_end.insert(0, x)
            else:
                match_days_end.append(x)  # first day first in the list
    dst_end = mktime((year, dst_rules["end"][0], match_days_end[0], dst_rules["end"][3], 0, 0, dst_rules["end"][1], 0))
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
    """ Class initialize the display and show text """

    def __init__(self, width=16, rows=6, lpixels=128, kpixels=64):
        self.rows = []
        self.dtxt = []
        self.time = 5
        self.row = 1
        self.dwidth = width
        self.drows = rows
        self.pix_w = lpixels
        self.pix_h = kpixels
        self.scr = DISP.SH1106_I2C(self.pix_w, self.pix_h, i2c)
        self.scr_txt = ""
        self.scr.poweron()
        self.scr.init_display()
        self.inverse = False

    async def l_txt_2_scr(self, text, time, row=1):
        self.time = time
        self.row = row
        self.dtxt.clear()
        self.rows.clear()
        self.scr_txt = [text[y - self.dwidth:y] for y in range(self.dwidth, len(text) + self.dwidth, self.dwidth)]
        for y in range(len(self.dtxt)):
            self.rows.append(self.dtxt[y])
        if len(self.rows) > self.drows:
            pages = len(self.dtxt) // self.drows
        else:
            pages = 1
        if pages == 1:
            for z in range(0, len(self.rows)):
                self.scr.text(self.rows[z], 0, self.row + z * 10, 1)

    async def txt_2_r(self, text, row, time):
        self.time = time
        if len(text) > self.dwidth:
            self.scr.text('Row too long', 0, 1 + row * 10, 1)
        elif len(text) <= self.dwidth:
            self.scr.text(text, 0, 1 + row * 10, 1)

    async def act_scr(self):
        self.scr.show()
        await asyncio.sleep(self.time)
        self.scr.init_display()

    async def contrast(self, contrast=255):
        if contrast > 1 or contrast < 255:
            self.scr.contrast(contrast)

    async def inv_colr(self, inverse=False):
        self.inverse = inverse
        self.scr.invert(inverse)

    async def rot_180(self, rotate=False):
        self.scr.rotate(rotate)

    async def d_frame(self):
        if self.inverse is False:
            self.scr.framebuf.rect(1, 1, self.pix_w - 1, self.pix_h - 1, 0xffff)
        else:
            self.scr.framebuf.rect(1, 1, self.pix_w - 1, self.pix_h - 1, 0x0000)

    async def d_undrl(self, row, width):
        rheight = self.pix_h / self.row
        x = 1
        y = 8 + (int(rheight * row))
        cwdth = int(8 * width)
        if self.inverse is False:
            self.scr.framebuf.hline(x, y, cwdth, 0xffff)
        else:
            self.scr.framebuf.hline(x, y, cwdth, 0x0000)

    async def res_scr(self):
        self.scr.reset()

    async def shut_scr(self):
        self.scr.poweroff()

    async def strt_scr(self):
        self.scr.poweron()


async def mqtt_up_l():
    global mqtt_up
    global mq_clnt

    while net.net_ok is False:
        gc.collect()
        await asyncio.sleep(5)

    if net.net_ok is True:
        config['subs_cb'] = upd_mqtt_stat
        config['connect_coro'] = mqtt_subs
        config['ssid'] = net.use_ssid
        config['wifi_pw'] = net.u_pwd
        MQTTClient.DEBUG = True
        mq_clnt = MQTTClient(config)
        try:
            await mq_clnt.connect()
        except OSError as e:
            log_errors("WiFi connect: %s" % e)
            print("Soft reboot caused error %s" % e)
            await asyncio.sleep(5)
            reset()
        while mqtt_up is False:
            await asyncio.sleep(5)
            try:
                await mq_clnt.connect()
                if mq_clnt.isconnected() is True:
                    mqtt_up = True
            except OSError as e:
                log_errors("MQTT Connect: %s" % e)
                if d_scr_act == 1:
                    print("MQTT error: %s" % e)
                    print("Config: %s" % config)
    n = 0
    while True:
        # await self.mqtt_subscribe()
        await asyncio.sleep(5)
        if d_scr_act == 1:
            print('mqtt-publish', n)
        await mq_clnt.publish('result', '{}'.format(n), qos=1)
        n += 1


async def mqtt_subs(mq_client):
    # If "mq_clnt" is missing, you get error from line 538 in MQTT_AS.py (1 given, expected 0)
    await mq_client.subscribe('$SYS/broker/uptime', 1)


def upd_mqtt_stat(topic, msg, retained):
    global bro_upt
    if d_scr_act == 1:
        print((topic, msg, retained))
    bro_upt = msg


async def s_what_i_do():
    # Output is REPL

    while True:
        print("\n1 ---------WIFI------------- 1")
        if s_net == 1:   # net.use_ssid,
            print("   WiFi Connected %s, signal strength: %s" % (net.net_ok,  net.strength))
            print("   IP-address: %s" % net.ip_a)
        if s_mqtt == 1:
            print("   MQTT Connected: %s, broker uptime: %s" % (mqtt_up, bro_upt))
        print("   Memory free: %s, allocated: %s" % (gc.mem_free(), gc.mem_alloc()))
        print("   Heap info %s, hall sensor %s, raw-temp %sC" % (esp32.idf_heap_info(esp32.HEAP_DATA),
                                                                 esp32.hall_sensor(),
                                                                 "{:.1f}".format(
                                                                     ((float(esp32.raw_temperature()) - 32.0)
                                                                      * 5 / 9))))
        print("2 ---------SENSORS----------- 2")
        print("   Sensor 1: %s " % temp_s1_av)
        print("   Sensor 2: %s " % temp_s2_av)
        print("   Sensor 3: %s " % temp_s3_av)
        print("   Sensor 4: %s " % temp_s4_av)
        print("   Sensor 5: %s " % temp_s5_av)
        print("\n")
        await asyncio.sleep(5)


# Adjust speed to low heat production, max 240000000, normal 160000000, min with Wi-Fi 80000000
#  freq(240000000)
freq(80000000)

# Decode to base64
s1_addr = ubinascii.a2b_base64(s1_addr)
s2_addr = ubinascii.a2b_base64(s2_addr)
s3_addr = ubinascii.a2b_base64(s3_addr)
s4_addr = ubinascii.a2b_base64(s4_addr)
s5_addr = ubinascii.a2b_base64(s5_addr)

# DS18B20 pin. Each sensor has unique ID, so you can use just one pin. This is for 5 sensors.
ds_roms = ds18x20.DS18X20(onewire.OneWire(Pin(DS_PIN)))
found_roms = ds_roms.scan()
if len(found_roms) < 5:
    log_errors("Error: should have 5 sensors, found %s" % len(found_roms))
    raise Exception("Error: should have 5 sensors, found %s" % len(found_roms))
# Match sensor addresses to runtimejson addresses
if not s1_addr and s2_addr and s3_addr and s4_addr and s5_addr in found_roms:
    log_errors("Sensor addresses do not match to found sensors! %s" % found_roms)
    raise Exception("Sensor addresses do not match to found sensors! %s" % found_roms)


# Network handshake
net = WNET.ConnectWiFi(sid1, pwd1, sid2, pwd2, ntp_s, dhcp_n, s_wbrpl, wbrpl_pwd)
i2c = SoftI2C(scl=Pin(I2C_SCL_PIN), sda=Pin(I2C_SDA_PIN))

#  OLED display
try:
    dp = Displayme()
except OSError as err:
    log_errors("OLED init: %s" % err)
    raise Exception("Error: %s - OLED Display init error!" % err)


def f_sens():
    # Shows connected sensors addresses and converts them to base64 for runtimeconfig.json
    ds_found = ds_roms.scan()
    for ds in ds_found:
        ds_roms.convert_temp()
        print("Found sensors are: %s" % ds)
        print("Encoded base64 addresses for runtimeconfig: %s" % ubinascii.b2a_base64(ds).decode('utf-8').strip())
        print("Temperature readings: %s" % ds_roms.read_temp(ds))


async def r_sen_l():
    global temp_s1_av, temp_s2_av, temp_s3_av, temp_s4_av, temp_s5_av
    temp_s1_l = []
    temp_s2_l = []
    temp_s3_l = []
    temp_s4_l = []
    temp_s5_l = []

    #  Read values from sensor once per second, add them to the array, delete oldest when size 60 (seconds)
    while True:
        try:
            ds_roms.convert_temp()
            temp_s1_l.append(ds_roms.read_temp(s1_addr) + temp_s1_corr)
            temp_s2_l.append(ds_roms.read_temp(s2_addr) + temp_s2_corr)
            temp_s3_l.append(ds_roms.read_temp(s3_addr) + temp_s3_corr)
            temp_s4_l.append(ds_roms.read_temp(s4_addr) + temp_s4_corr)
            temp_s5_l.append(ds_roms.read_temp(s5_addr) + temp_s5_corr)
        except ValueError as e:
            log_errors("Value error in read_sensors_loop: %s" % e)
        else:
            if len(temp_s1_l) >= 60:
                temp_s1_l.pop(0)
            if len(temp_s2_l) >= 60:
                temp_s2_l.pop(0)
            if len(temp_s3_l) >= 60:
                temp_s3_l.pop(0)
            if len(temp_s4_l) >= 60:
                temp_s4_l.pop(0)
            if len(temp_s5_l) >= 60:
                temp_s5_l.pop(0)
            if len(temp_s1_l) > 1:
                temp_s1_av = round(sum(temp_s1_l) / len(temp_s1_l), 1)
            if len(temp_s2_l) > 1:
                temp_s2_av = round(sum(temp_s2_l) / len(temp_s2_l), 1)
            if len(temp_s3_l) > 1:
                temp_s3_av = round(sum(temp_s3_l) / len(temp_s3_l), 1)
            if len(temp_s4_l) > 1:
                temp_s4_av = round(sum(temp_s4_l) / len(temp_s4_l), 1)
            if len(temp_s5_l) > 1:
                temp_s5_av = round(sum(temp_s5_l) / len(temp_s5_l), 1)
            gc.collect()
            await asyncio.sleep(1)


async def mqtt_pub_l():
    #  Publish only valid average values.

    while True:
        if mqtt_up is False:
            await asyncio.sleep(10)
        else:
            await asyncio.sleep(mqtt_ival)
            if -40 < temp_s1_av < 120:
                await mq_clnt.publish(t_temp_s1, str(temp_s1_av), retain=0, qos=0)
            if -40 < temp_s2_av < 120:
                await mq_clnt.publish(t_temp_s2, str(temp_s2_av), retain=0, qos=0)
            if -40 < temp_s3_av < 120:
                await mq_clnt.publish(t_temp_s3, str(temp_s3_av), retain=0, qos=0)
            if -40 < temp_s4_av < 120:
                await mq_clnt.publish(t_temp_s4, str(temp_s4_av), retain=0, qos=0)
            if -40 < temp_s5_av < 120:
                await mq_clnt.publish(t_temp_s5, str(temp_s5_av), retain=0, qos=0)


# For MQTT_AS
config['server'] = mqtt_s
config['user'] = mqtt_usr
config['password'] = mqtt_pwd
config['port'] = mqtt_prt
config['client_id'] = client_id
if mqtt_use_ssl == "True":
    config['ssl'] = True
else:
    config['ssl'] = False

mq_clnt = MQTTClient(config)


async def disp_l():
    while True:
        await dp.rot_180(True)
        await dp.txt_2_r("  %s %s" % (resolve_date()[2], resolve_date()[0]), 0, 5)
        await dp.txt_2_r("    %s" % resolve_date()[1], 1, 5)
        await dp.txt_2_r("S1:%s S2:%s" % ("{:.1f}".format(temp_s1_av), "{:.1f}".format(temp_s2_av)), 2, 5)
        await dp.txt_2_r("S3:%s" % "{:.1f}".format(temp_s3_av), 3, 5)
        await dp.txt_2_r("S4:%s S5:%s" % ("{:.1f}".format(temp_s4_av), "{:.1f}".format(temp_s5_av)), 4, 5)
        # row 5 await display.text_to_row("Alarms:%s " % alarms, 5, 5)
        await dp.act_scr()
        await asyncio.sleep(1)


async def main():
    loop = asyncio.get_event_loop()
    if s_net == 1:
        loop.create_task(net.net_upd_loop())
    if d_scr_act == 1:
        loop.create_task(s_what_i_do())
    if s_mqtt == 1:
        loop.create_task(mqtt_up_l())
        loop.create_task(mqtt_pub_l())
    loop.create_task(r_sen_l())
    loop.create_task(disp_l())
    loop.run_forever()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except MemoryError as err:
        log_errors(err)
        reset()
