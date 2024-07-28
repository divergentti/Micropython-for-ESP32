"""
This script is used for I2C connected OLED display, BME680 temperature/rh/pressure/voc sensor
MH-Z19B CO2 NDIR-sensor, PMS9103M particle sensor. Asynchronous code.

See documentation at GitHub.

For webrepl, remember to execute import webrepl_setup one time.

Version 0.2 Jari Hiltunen -  28.07.2024
"""
import json
from machine import SoftI2C, Pin, freq, reset, ADC, TouchPad
import uasyncio as asyncio
from utime import time, mktime, localtime, sleep
import gc
import os
import drivers.WIFICONN_AS as WIFINET
import drivers.BME680 as BMES
import drivers.SH1106 as DP
import drivers.PMS9103M_AS as PARTS
import drivers.MHZ19B_AS as CO2
from drivers.AQI import AQI
from json import load
from drivers.MQTT_AS import MQTTClient, config
from machine import reset_cause
gc.collect()

last_error = None


def log_errors(err_in):
    global last_error
    last_error = err_in

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
    from parameters import I2C_SCL_PIN, I2C_SDA_PIN, MH_UART, MH_RX, MH_TX, PMS_UART, PMS_RX, PMS_TX
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
        pw1 = data['PASSWORD1']
        pw2 = data['PASSWORD2']
        mqtt_s = data['MQTT_SERVER']
        mqtt_pwd = data['MQTT_PASSWORD']
        mqtt_u = data['MQTT_USER']
        mqtt_p = data['MQTT_PORT']
        mqtt_ssl = data['MQTT_SSL']
        mqtt_ival = data['MQTT_INTERVAL']
        client_id = data['CLIENT_ID']
        t_err = data['TOPIC_ERRORS']
        webrepl_pwd = data['WEBREPL_PASSWORD']
        ntp_s = data['NTPSERVER']
        dhcp_n = data['DHCP_NAME']
        start_wbl = data['START_WEBREPL']
        start_net = data['START_NETWORK']
        start_mqtt = data['START_MQTT']
        s_upd_ival = data['SCREEN_UPDATE_INTERVAL']
        deb_scr_a = data['DEBUG_SCREEN_ACTIVE']
        scr_tout = data['SCREEN_TIMEOUT']
        t_temp = data['TOPIC_TEMP']
        temp_thold = data['TEMP_TRESHOLD']
        temp_corr = data['TEMP_CORRECTION']
        t_rh = data['TOPIC_RH']
        rh_thold = data['RH_TRESHOLD']
        rh_corr = data['RH_CORRECTION']
        t_press = data['TOPIC_PRESSURE']
        press_corr = data['PRESSURE_CORRECTION']
        press_thold = data['PRESSURE_TRESHOLD']
        t_gasr = data['TOPIC_RGAS']
        gasr_corr = data['RGAS_CORRECTION']
        gasr_thold = data['RGAS_TRESHOLD']
        t_co2 = data['TOPIC_CO2']
        co2_corr = data['CO2_CORRECTION']
        co2_thold = data['CO2_TRESHOLD']
        t_airq = data['T_AIRQ']
        t_pm1_0 = data['T_PM1_0']
        t_pm1_0_atm = data['T_PM1_0_ATM']
        t_pm2_5 = data['T_PM2_5']
        t_pm2_5_atm = data['T_PM2_5_ATM']
        t_pm10_0 = data['T_PM10_0']
        t_pm10_0_atm = data['T_PM10_0_ATM']
        t_pcnt_0_3 = data['T_PCNT_0_3']
        t_pcnt_0_5 = data['T_PCNT_0_5']
        t_pcnt_1_0 = data['T_PCNT_1_0']
        t_pcnt_2_5 = data['T_PCNT_2_5']
        t_pcnt_5_0 = data['T_PCNT_5_0']
        t_pcnt_10_0 = data['T_PCNT_10_0']
        aq_thold = data['AQ_THOLD']
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

# Globals
mqtt_up = False
broker_uptime = 0
co2_average = 0
temp_average = 0
rh_average = 0
pressure_average = 0
gas_average = 0
bme_s_f = False
mhz19_f = False
pms_f = False
scr_f = False
mqtt_last_update = 0


# For MQTT_AS
config['server'] = mqtt_s
config['user'] = mqtt_u
config['password'] = mqtt_pwd
config['port'] = mqtt_p
config['client_id'] = client_id
if mqtt_ssl == "True":
    config['ssl'] = True
else:
    config['ssl'] = False
mq_clnt = MQTTClient(config)


def weekday(year, month, day):
    # Returns weekday. Thanks to 2DOF @ GitHub
    t = [0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4]
    year -= month < 3
    return (year + int(year / 4) - int(year / 100) + int(year / 400) + t[month - 1] + day) % 7


def resolve_dst():
    # For fucking EU idiots keeping this habit running!
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


class DisplayMe(object):
    """ Class initialize the display and show text, using I2C """

    def __init__(self, width=16, rows=6, lpixels=128, kpixels=64):
        self.rows = []
        self.dtxt = []
        self.time = 5
        self.row = 1
        self.dwidth = width
        self.drows = rows
        self.pix_w = lpixels
        self.pix_h = kpixels
        self.scr = DP.SH1106_I2C(self.pix_w, self.pix_h, i2c)  # support SPI too
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
            truncated_text = text[:self.dwidth]  # Truncate the text to fit the width
            self.scr.text(truncated_text, 0, 1 + row * 10, 1)
        else:
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


class AirQuality(object):
    def __init__(self, pmssensor):
        self.aqinndex = None
        self.pms = pmssensor
        self.upd_ival = pms.read_interval + 1

    async def upd_aq_loop(self):
        while True:
            if self.pms.pms_dictionary is not None:
                if (self.pms.pms_dictionary['PM2_5_ATM'] != 0) and (self.pms.pms_dictionary['PM10_0_ATM'] != 0):
                    self.aqinndex = (AQI.aqi(self.pms.pms_dictionary['PM2_5_ATM'],
                                             self.pms.pms_dictionary['PM10_0_ATM']))
            await asyncio.sleep(self.upd_ival)


async def mqtt_up_loop():
    global mqtt_up
    global mq_clnt

    while net.net_ok is False:
        gc.collect()
        await asyncio.sleep(5)

    if net.net_ok is True:
        config['subs_cb'] = update_mqtt_status
        config['connect_coro'] = mqtt_subscribe
        config['ssid'] = net.use_ssid
        config['wifi_pw'] = net.u_pwd
        MQTTClient.DEBUG = True
        mq_clnt = MQTTClient(config)
        try:
            await mq_clnt.connect()
        except OSError as err:
            log_errors("Soft reboot caused error %s: %s" % err)
            if deb_scr_a == 1:
                print("Soft reboot caused error %s ", err)
            await asyncio.sleep(5)
            reset()
        while mqtt_up is False:
            await asyncio.sleep(5)
            try:
                await mq_clnt.connect()
                if mq_clnt.isconnected() is True:
                    mqtt_up = True
            except OSError as err:
                log_errors("MQTT connect error: %s: %s" % err)
                log_errors("Config: %s" % config)
                if deb_scr_a == 1:
                    print("MQTT error: %s" % err)

    n = 0
    while True:
        # await self.mqtt_subscribe()
        await asyncio.sleep(5)
        if deb_scr_a == 1:
            print('mqtt-publish', n)
        await mq_clnt.publish('result', '{}'.format(n), qos=1)
        n += 1

async def mqtt_subscribe(client):
    # If "client" is missing, you get error from line 538 in MQTT_AS.py (1 given, expected 0)
    await client.subscribe('$SYS/broker/uptime', 1)

def update_mqtt_status(topic, msg, retained):
    global broker_uptime
    if deb_scr_a == 1:
        print((topic, msg, retained))
    broker_uptime = msg


async def show_what_i_do():
    # Output is REPL

    while True:
        print("\n1 ---------WIFI------------- 1")
        if start_net == 1:
            print("   WiFi Connected %s, hotspot: hidden, signal strength: %s" % (net.net_ok,  net.strength))
            print("   IP-address: %s" % net.ip_a)
        if start_mqtt == 1:
            print("   MQTT Connected: %s, broker uptime: %s" % (mqtt_up, broker_uptime))
            if mqtt_up is True:
                print("   MQTT messages sent %s seconds ago. " % (time() - mqtt_last_update))
        print("   Memory free: %s, allocated: %s" % (gc.mem_free(), gc.mem_alloc()))
        print("2 -------SENSORDATA--------- 2")
        if (temp_average is not None) and (rh_average is not None) and (gas_average is not None):
            print("   Temp: %sC, Rh: %s, GasR: %s" % (temp_average, rh_average, gas_average))
        if co2s.co2_average is not None:
            print("   CO2 is %s" % co2s.co2_average)
        if aq.aqinndex is not None:
            print("   AQ Index: %s" % ("{:.1f}".format(aq.aqinndex)))
        if isinstance(pms.pms_dictionary, dict):
            print("   PM1:%s (%s) PM2.5:%s (%s)" % (pms.pms_dictionary['PM1_0'], pms.pms_dictionary['PM1_0_ATM'],
                                                    pms.pms_dictionary['PM2_5'], pms.pms_dictionary['PM2_5_ATM']))
            print("   PM10: %s (ATM: %s)" % (pms.pms_dictionary['PM10_0'], pms.pms_dictionary['PM10_0_ATM']))
            print("   %s < 0.3 & %s <0.5 " % (pms.pms_dictionary['PCNT_0_3'], pms.pms_dictionary['PCNT_0_5']))
            print("   %s < 1.0 & %s < 2.5" % (pms.pms_dictionary['PCNT_1_0'], pms.pms_dictionary['PCNT_2_5']))
            print("   %s < 5.0 & %s < 10.0" % (pms.pms_dictionary['PCNT_5_0'], pms.pms_dictionary['PCNT_10_0']))
        print("3 ---------FAULTS------------- 3")
        print("   Last error: %s " % last_error)
        if bme_s_f:
            print("BME680 sensor faulty!")
        if mhz19_f:
            print("MHZ19 sensor faulty!")
        if pms_f:
            print("PMS9103M sensor faulty!")
        if scr_f:
            print("Screen faulty!")

        print("\n")
        await asyncio.sleep(5)


# Adjust speed to low heat production, max 240000000, normal 160000000, min with Wi-Fi 80000000
#  freq(240000000)
freq(80000000)
# freq(160000000)

# Network handshake
net = WIFINET.ConnectWiFi(sid1, pw1, sid2, pw2, ntp_s, dhcp_n, start_wbl, webrepl_pwd)
i2c = SoftI2C(scl=Pin(I2C_SCL_PIN), sda=Pin(I2C_SDA_PIN))

# BME-sensor
try:
    bmes = BMES.BME680_I2C(i2c=i2c)
except OSError as err:  # open failed
    log_errors("Error: %s - BME sensor init error!" % err)
    if deb_scr_a == 1:
        print("Error: %s - BME sensor init error!", err)
    bme_s_f = True

# Particle sensor
try:
    pms = PARTS.PSensorPMS9103M(uart=PMS_UART, rxpin=PMS_RX, txpin=PMS_TX)
    if reset_cause() == 1:
        del pms
        pms = PARTS.PSensorPMS9103M(uart=PMS_UART, rxpin=PMS_RX, txpin=PMS_TX)
    aq = AirQuality(pms)
except OSError as err:
    log_errors("Error: %s - Particle sensor init error!" % err)
    if deb_scr_a == 1:
        print("Error: %s - Particle sensor init error!" % err)
    pms_f = True

# CO2 sensor
try:
    co2s = CO2.MHZ19bCO2(uart=MH_UART, rxpin=MH_RX, txpin=MH_TX)
    if reset_cause() == 1:
        del co2s
        sleep(5)  # 2 is not enough!
        co2s = CO2.MHZ19bCO2(uart=MH_UART, rxpin=MH_RX, txpin=MH_TX)
except OSError as err:
    log_errors("Error: %s - MHZ19 sensor init error!" % err)
    if deb_scr_a == 1:
        print("Error: %s - MHZ19 sensor init error!" % err)
    mhz19_f = True


# Display
try:
    display = DisplayMe()
except OSError as err:
    log_errors("Error: %s - Display init error!" % err)
    if deb_scr_a == 1:
        print("Error: %s - Display init error!" % err)
    scr_f = True

# Touch thing - future reservation to activate the screen
# touch = TouchPad(Pin(TOUCH_PIN))


async def upd_status_loop():
    # Other sensor loops are in their drivers, this is for BME
    global temp_average
    global rh_average
    global pressure_average
    global gas_average
    temp_list = []
    rh_list = []
    press_list = []
    gas_list = []

    while True:
        if not bme_s_f:
            try:
                temp_list.append(round(float(bmes.temperature)) + temp_corr)
                rh_list.append(round(float(bmes.humidity)) + rh_corr)
                press_list.append(round(float(bmes.pressure)) + press_corr)
                gas_list.append(round(float(bmes.gas)))
            except ValueError as err:
                if deb_scr_a == 1:
                    print("BME sensor loop error: %s" % err)
                    log_errors("BME se sensor loop error" % err)
                    pass
            if len(temp_list) >= 60:
                temp_list.pop(0)
            if len(rh_list) >= 60:
                rh_list.pop(0)
            if len(press_list) >= 60:
                press_list.pop(0)
            if len(gas_list) >= 60:
                gas_list.pop(0)
            if len(temp_list) > 1:
                temp_average = round(sum(temp_list) / len(temp_list), 1)
            if len(rh_list) > 1:
                rh_average = round(sum(rh_list) / len(rh_list), 1)
            if len(press_list) > 1:
                pressure_average = round(sum(press_list) / len(press_list), 1)
            if len(gas_list) > 1:
                gas_average = round(sum(gas_list) / len(gas_list), 1)
            gc.collect()
            gc.threshold(gc.mem_free() // 4 + gc.mem_alloc())
        await asyncio.sleep(1)


async def mqtt_up_l():
    global mqtt_up
    global mq_clnt
    global config

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
                if deb_scr_a == 1:
                    print("MQTT error: %s" % e)
                    print("Config: %s" % config)
    n = 0
    while True:
        # await self.mqtt_subscribe()
        await asyncio.sleep(10)
        if deb_scr_a == 1:
            print('mqtt-publish test', n)
        await mq_clnt.publish('result', '{}'.format(n), qos=1)
        n += 1


async def mqtt_pub_l():
    global mqtt_last_update

    while True:
        if mqtt_up is False:
            await asyncio.sleep(1)
        elif (time() - mqtt_last_update) >= mqtt_ival:
            if -40 < temp_average < 120:
                await mq_clnt.publish(t_temp, str(temp_average), retain=0, qos=0)
            if 0 < rh_average <= 100:
                await mq_clnt.publish(t_rh, str(rh_average), retain=0, qos=0)
            if 0 < pressure_average < 5000:
                await mq_clnt.publish(t_press, str(pressure_average), retain=0, qos=0)
            if 0 < gas_average < 99999999999999:
                await mq_clnt.publish(t_gasr, str(gas_average), retain=0, qos=0)

            if (pms.pms_dictionary is not None) and ((time() - pms.startup_time) > pms.read_interval):
                await mq_clnt.publish(t_pm1_0, str(pms.pms_dictionary['PM1_0']), retain=0, qos=0)
                await mq_clnt.publish(t_pm1_0_atm, str(pms.pms_dictionary['PM1_0_ATM']), retain=0, qos=0)
                await mq_clnt.publish(t_pm2_5, str(pms.pms_dictionary['PM2_5']), retain=0, qos=0)
                await mq_clnt.publish(t_pm2_5_atm, str(pms.pms_dictionary['PM2_5_ATM']), retain=0, qos=0)
                await mq_clnt.publish(t_pm10_0, str(pms.pms_dictionary['PM10_0']), retain=0, qos=0)
                await mq_clnt.publish(t_pm10_0_atm, str(pms.pms_dictionary['PM10_0_ATM']), retain=0, qos=0)
                await mq_clnt.publish(t_pcnt_0_3, str(pms.pms_dictionary['PCNT_0_3']), retain=0, qos=0)
                await mq_clnt.publish(t_pcnt_0_5, str(pms.pms_dictionary['PCNT_0_5']), retain=0, qos=0)
                await mq_clnt.publish(t_pcnt_1_0, str(pms.pms_dictionary['PCNT_1_0']), retain=0, qos=0)
                await mq_clnt.publish(t_pcnt_2_5, str(pms.pms_dictionary['PCNT_2_5']), retain=0, qos=0)
                await mq_clnt.publish(t_pcnt_5_0, str(pms.pms_dictionary['PCNT_5_0']), retain=0, qos=0)
                await mq_clnt.publish(t_pcnt_10_0, str(pms.pms_dictionary['PCNT_10_0']), retain=0, qos=0)

            if aq.aqinndex is not None:
                await mq_clnt.publish(t_airq, str(aq.aqinndex), retain=0, qos=0)

            if not mhz19_f and (co2s.co2_average is not None):
                await mq_clnt.publish(t_co2, str(co2s.co2_average), retain=0, qos=0)

            mqtt_last_update = time()

            await asyncio.sleep(1)
            gc.collect()
            gc.threshold(gc.mem_free() // 4 + gc.mem_alloc())
        else:
            await asyncio.sleep(1)


async def mqtt_subs(mq_client):
    # If "mq_clnt" is missing, you get error from line 538 in MQTT_AS.py (1 given, expected 0)
    await mq_client.subscribe('$SYS/broker/uptime', 1)


def upd_mqtt_stat(topic, msg, retained):
    global broker_uptime
    if deb_scr_a == 1:
        print((topic, msg, retained))
    broker_uptime = msg


async def disp_l():

    while True:
        await display.rot_180(True)

        # page 1

        await display.txt_2_r("  %s %s" % (resolve_date()[2], resolve_date()[0]), 0, 5)
        await display.txt_2_r("    %s" % resolve_date()[1], 1, 5)
        if (temp_average > 0) and (rh_average > 0):
            await display.txt_2_r("%sC Rh:%s" % ("{:.1f}".format(temp_average), "{:.1f}".format(rh_average)), 2, 5)
        else:
            await display.txt_2_r("Waiting values", 2, 5)
        if co2s.co2_average is not None:
            await display.txt_2_r("CO2:%s" % "{:.1f}".format(co2s.co2_average), 3, 5)
        if gas_average > 0:
            await display.txt_2_r("GasR:%s" % "{:.1f}".format(gas_average), 4, 5)
        if aq.aqinndex is not None:
            await display.txt_2_r("AirQuality:%s " % aq.aqinndex, 5, 5)
        await display.act_scr()
        await asyncio.sleep(1)

        # page 2
        if pms.pms_dictionary is not None:
            await display.txt_2_r("PM1_0 :%s" % str(pms.pms_dictionary['PM1_0']), 0, 5)
            await display.txt_2_r("PM2_5 :%s" % str(pms.pms_dictionary['PM1_0_ATM']), 1, 5)
            await display.txt_2_r("PM10_0:%s" % str(pms.pms_dictionary['PM10_0']), 2, 5)
            await display.txt_2_r("PM1_0_ATM:%s" % str(pms.pms_dictionary['PM10_0_ATM']), 3, 5)
            await display.txt_2_r("PM2_5_ATM:%s" % str(pms.pms_dictionary['PM2_5_ATM']), 4, 5)
            await display.txt_2_r("PM10_0_ATM:%s" % str(pms.pms_dictionary['PM10_0_ATM']), 5, 5)
            await display.act_scr()
            await asyncio.sleep(1)

        # page 3

            await display.txt_2_r("PCNT_0_3:%s" % str(pms.pms_dictionary['PCNT_0_3']), 0, 5)
            await display.txt_2_r("PCNT_0_5:%s" % str(pms.pms_dictionary['PCNT_0_5']), 1, 5)
            await display.txt_2_r("PCNT_1_0:%s" % str(pms.pms_dictionary['PCNT_1_0']), 2, 5)
            await display.txt_2_r("PCNT_2_5:%s" % str(pms.pms_dictionary['PCNT_2_5']), 3, 5)
            await display.txt_2_r("PCNT_5_0:%s" % str(pms.pms_dictionary['PCNT_5_0']), 4, 5)
            await display.txt_2_r("PCNT_10_0:%s" % str(pms.pms_dictionary['PCNT_10_0']), 5, 5)
            await display.act_scr()
            await asyncio.sleep(1)

        # page 4

        await display.txt_2_r("WIFI:%s" % net.strength, 0, 5)
        await display.txt_2_r("WebRepl:%s" % net.webrepl_started, 1, 5)
        await display.txt_2_r("MQTT up:%s" % mqtt_up, 2, 5)
        await display.txt_2_r("Broker:%s" % broker_uptime, 3, 5)
        await display.txt_2_r("Memfree:%s" % gc.mem_free(), 4, 5)
        await display.txt_2_r("Err:%s" % last_error, 5, 5)
        await display.act_scr()
        await asyncio.sleep(1)


async def watchdog():
    #  Keep system up and running, else reboot and try to recover
    bme_fail = 0
    pms_fail = 0
    mhz_fail = 0
    l_temp = 0
    l_rh = 0
    l_pressure = 0
    l_rgas = 0
    l_co2 = 0
    l_aqi = 0

    while True:

        if not bme_s_f:
            l_temp = bmes.temperature
            l_rh = bmes.humidity
            l_pressure = bmes.pressure
            l_rgas = bmes.gas
        if not mhz19_f:
            l_co2 = co2s.co2_value
        if not pms_f:
            l_aqi = aq.aqinndex

        await asyncio.sleep(mqtt_ival * 10)  # Interval for the watchdoc comparison (10 min)

        if not bme_s_f:
            if l_temp == bmes.temperature:
                bme_fail += 1
            elif l_rh == bmes.humidity:
                bme_fail += 1
            elif l_pressure == bmes.pressure:
                bme_fail += 1
            elif l_rgas == bmes.gas:
                bme_fail += 1
        if not mhz19_f:
            if l_co2 == co2s.co2_value:
                mhz_fail += 1
        if not pms_f:
            if l_aqi == aq.aqinndex:
                pms_fail += 1

        if bme_fail >= 4:
            log_errors("BME keeps failing, resetting")
            if deb_scr_a == 1:
                print("Time not synchronized!")
            reset()
        elif mhz_fail >= 1:
            log_errors("MH-Z19B keeps failing, resetting")
            if deb_scr_a == 1:
                print("Time not synchronized!")
            reset()
        elif pms_fail >= 1:
            log_errors("PMS keeps failing, resetting")
            if deb_scr_a == 1:
                print("Time not synchronized!")
            reset()


async def main():
    loop = asyncio.get_event_loop()
    if start_net == 1:
        loop.create_task(net.net_upd_loop())
    if deb_scr_a == 1:
        loop.create_task(show_what_i_do())
    if start_mqtt == 1:
        loop.create_task(mqtt_up_l())
        loop.create_task(mqtt_pub_l())
    loop.create_task(pms.read_async_loop())
    loop.create_task(co2s.read_co2_loop())
    loop.create_task(aq.upd_aq_loop())
    loop.create_task(upd_status_loop())
    loop.create_task(disp_l())
    loop.create_task(watchdog())
    loop.run_forever()

if __name__ == "__main__":
    asyncio.run(main())
