"""
This script is used for I2C connected OLED display, BME680 temperature/rh/pressure/voc sensor
MH-Z19B CO2 NDIR-sensor, PMS9103M particle sensor. Asynchronous code.

Tested with Chip ESP32-D0WD-V3 (revision v3.1) & ESP32_GENERIC-20240602-v1.23.0.bin

See documentation at GitHub.

For webrepl, remember to execute import webrepl_setup one time.

Version 0.4 Jari Hiltunen -  6.9.2024
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
from machine import WDT
gc.collect()
last_error = None

if reset_cause() == 1:  # we do this for some UART issues
    reset()

def log_errors(err_in):
    global last_error
    last_error = err_in

    filename = "/errors.csv"
    max_file_size_bytes = 1024  # 1KB

    try:
        # Open file in append mode and write the error
        with open(filename, 'a+') as logf:
            logf.write(f"{resolve_date()[0]},{str(err_in)}\r\n")
    except OSError as e:
        print(f"Cannot write to {filename}: {e}")
        raise

    # Check the file size and shrink/delete if needed
    try:
        file_stat = os.stat(filename)
        file_size_bytes = file_stat[6]  # Index 6 corresponds to file size

        if file_size_bytes > max_file_size_bytes:
            with open(filename, 'r') as file:
                lines = file.readlines()
                # Keep only the last 1000 lines
                lines = lines[-1000:]

            with open(filename, 'w') as file:
                file.writelines(lines)

    except OSError as e:
        if e.args[0] == 2:  # File not found error
            # File doesn't exist, create it
            with open(filename, 'w') as file:
                pass  # Just create an empty file
        else:
            print(f"Error while checking/shrinking the log file: {e}")
            raise



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
temp_average = 0
rh_average = 0
pressure_average = 0
gas_average = 0
bmes_f = False
mhz19_f = False
pms_f = False
scr_f = False
mqtt_last_update = 0
pms_read_errors = 0
mhz_read_errors = 0
bme_read_errors = 0


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
    """Calculates the weekday for a given date. Monday is 0 and Sunday is 6."""
    t = [0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4]
    year -= month < 3
    return (year + int(year / 4) - int(year / 100) + int(year / 400) + t[month - 1] + day) % 7


def find_last_weekday(year, month, target_weekday):
    """Finds the last occurrence of a specific weekday in a given month."""
    days_in_month = 30 if month in [4, 6, 9, 11] else 31
    if month == 2:
        # Simple leap year calculation
        days_in_month = 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28

    # Iterate backwards from the last day of the month
    for day in range(days_in_month, 0, -1):
        if weekday(year, month, day) == target_weekday:
            return day
    return None


def find_nth_weekday(year, month, target_weekday, occurrence):
    """Finds the nth occurrence of a specific weekday in a given month."""
    count = 0
    for day in range(1, 32):  # Assume at most 31 days
        if weekday(year, month, day) == target_weekday:
            count += 1
            if count == occurrence:
                return day
    return None


def resolve_dst():
    """Calculates the local time considering DST."""
    year, month, day, hour, minute, second, wday, yday = localtime()[:8]

    # Define the DST rules for the time zone
    dst_rules = {
        "begin": (dst_b_M, dst_b_D, dst_b_OCC, dst_b_time),  # (month, weekday, occurrence, time)
        "end": (dst_e_M, dst_e_D, dst_e_OCC, dst_e_time),  # (month, weekday, occurrence, time)
        "timezone": dst_tzone,  # hours from UTC during normal (winter) time
        "offset": 1  # hours to be added when DST is active
    }

    # Find the start and end of DST
    if dst_rules["begin"][2] == 2:  # If the occurrence is "last"
        dst_begin_day = find_last_weekday(year, dst_rules["begin"][0], dst_rules["begin"][1])
    else:
        dst_begin_day = find_nth_weekday(year, dst_rules["begin"][0], dst_rules["begin"][1], dst_rules["begin"][2])

    if dst_rules["end"][2] == 2:  # If the occurrence is "last"
        dst_end_day = find_last_weekday(year, dst_rules["end"][0], dst_rules["end"][1])
    else:
        dst_end_day = find_nth_weekday(year, dst_rules["end"][0], dst_rules["end"][1], dst_rules["end"][2])

    # Calculate mktime for DST start and end times
    dst_begin = mktime((year, dst_rules["begin"][0], dst_begin_day, dst_rules["begin"][3], 0, 0, 0, 0))
    dst_end = mktime((year, dst_rules["end"][0], dst_end_day, dst_rules["end"][3], 0, 0, 0, 0))

    current_time = mktime(localtime())

    # Check if DST is active
    if dst_begin <= current_time <= dst_end:
        return localtime(current_time + 3600 * (dst_rules["timezone"] + dst_rules["offset"]))  # DST active
    else:
        return localtime(current_time + 3600 * dst_rules["timezone"])  # Standard time


def resolve_date():
    """Calculates the current date and time considering DST."""
    (year, month, mdate, hour, minute, second, wday, yday) = resolve_dst()
    weekdays = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']
    day = f"{mdate}.{month}.{year}"
    hours = f"{hour:02d}:{minute:02d}:{second:02d}"
    return day, hours, weekdays[wday]


class DisplayMe(object):
    """ Class to initialize the display and show text, using I2C """

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

    async def _draw_text_to_display(self, text_lines, row_offset=0):
        for z, line in enumerate(text_lines):
            self.scr.text(line, 0, row_offset + z * 10, 1)

    async def l_txt_2_scr(self, text, time, row=1):
        self.time = time
        self.row = row
        self.dtxt.clear()
        self.rows.clear()

        self.scr_txt = [text[y - self.dwidth:y] for y in range(self.dwidth, len(text) + self.dwidth, self.dwidth)]
        self.rows = self.scr_txt[:self.drows]
        pages = len(self.scr_txt) // self.drows if len(self.scr_txt) > self.drows else 1

        if pages == 1:
            await self._draw_text_to_display(self.rows, self.row)

    async def txt_2_r(self, text, row, time):
        self.time = time
        truncated_text = text[:self.dwidth] if len(text) > self.dwidth else text
        self.scr.text(truncated_text, 0, 1 + row * 10, 1)

    async def act_scr(self):
        self.scr.show()
        await asyncio.sleep(self.time)
        self.scr.init_display()

    async def contrast(self, contrast=255):
        if 1 < contrast < 255:
            self.scr.contrast(contrast)

    async def inv_colr(self, inverse=False):
        self.inverse = inverse
        self.scr.invert(inverse)

    async def rot_180(self, rotate=False):
        self.scr.rotate(rotate)

    async def d_frame(self):
        color = 0xFFFF if not self.inverse else 0x0000
        self.scr.framebuf.rect(1, 1, self.pix_w - 1, self.pix_h - 1, color)

    async def d_undrl(self, row, width):
        rheight = self.pix_h / self.drows
        x = 1
        y = 8 + int(rheight * row)
        cwdth = int(8 * width)
        color = 0xFFFF if not self.inverse else 0x0000
        self.scr.framebuf.hline(x, y, cwdth, color)

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
            if net.startup_time is not None:
                print("   Runtime: %s" % (time()-net.startup_time))
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
        print("   Last error : %s " % last_error)
        print("   BME read errors: %s" % bme_read_errors)
        print("   MHZ read errors: %s" % mhz_read_errors)
        print("   PMS read errors: %s" % pms_read_errors)
        if bmes_f:
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
# freq(80000000)
freq(160000000)

def init_sensor(sensor_func, sensor_name, fault_flag):
    try:
        sensor = sensor_func()
        log_errors(f"{sensor_name} initialized successfully.")
        return sensor, False
    except OSError as err:
        log_errors(f"Error: {sensor_name} init error! {err}")
        if deb_scr_a == 1:
            print(f"Error: {sensor_name} init error! {err}")
        return None, True


# Particle sensor - keep this first!
pms, pms_f = init_sensor(
    lambda: PARTS.PMS(rxpin=PMS_RX, txpin=PMS_TX, uart=PMS_UART),
    "Particle sensor",
    "pms_f"
)
if pms:
    pms.debug = True
    aq = AirQuality(pms)

# I2C-bus for BME sensor and other devices
i2c = SoftI2C(scl=Pin(I2C_SCL_PIN), sda=Pin(I2C_SDA_PIN))

# BME-sensor
bmes, bmes_f = init_sensor(
    lambda: BMES.BME680_I2C(i2c=i2c),
    "BME680 sensor",
    "bme_s_f"
)

# CO2 sensor
co2s, mhz19_f = init_sensor(
    lambda: CO2.MHZ19bCO2(uart=MH_UART, rxpin=MH_RX, txpin=MH_TX),
    "MHZ19 CO2 sensor",
    "mhz19_f"
)

# Display
display, scr_f = init_sensor(
    lambda: DisplayMe(),
    "Display",
    "scr_f"
)

# Network handshake
if start_net == 1:
    net = WIFINET.ConnectWiFi(sid1, pw1, sid2, pw2, ntp_s, dhcp_n, start_wbl, webrepl_pwd)



async def upd_status_loop():
    global temp_average, rh_average, pressure_average, gas_average, bme_read_errors

    temp_list = []
    rh_list = []
    press_list = []
    gas_list = []
    max_len = 60

    def update_list(sensor_list, value):
        sensor_list.append(value)
        if len(sensor_list) > max_len:
            sensor_list.pop(0)
        if len(sensor_list) > 1:
            return round(sum(sensor_list) / len(sensor_list), 1)
        return None

    while True:
        if not bmes_f:
            try:
                temp = round(float(bmes.temperature)) + temp_corr
                rh = round(float(bmes.humidity)) + rh_corr
                press = round(float(bmes.pressure)) + press_corr
                gas = round(float(bmes.gas))

                temp_average = update_list(temp_list, temp)
                rh_average = update_list(rh_list, rh)
                pressure_average = update_list(press_list, press)
                gas_average = update_list(gas_list, gas)

            except ValueError as err:
                bme_read_errors += 1
                if deb_scr_a == 1:
                    print(f"BME sensor loop error: {err}")
                log_errors(f"BME sensor loop error: {err}")

            if len(temp_list) % max_len == 0:
                gc.collect()

        await asyncio.sleep(1)


async def mqtt_up_l():
    global mqtt_up
    global mq_clnt
    global config

    retry_count = 0
    max_retries = 5

    while not net.net_ok:
        gc.collect()
        await asyncio.sleep(5)

    if net.net_ok:
        config['subs_cb'] = upd_mqtt_stat
        config['connect_coro'] = mqtt_subs
        config['ssid'] = net.use_ssid
        config['wifi_pw'] = net.u_pwd
        MQTTClient.DEBUG = True
        mq_clnt = MQTTClient(config)

        while retry_count < max_retries:
            try:
                await mq_clnt.connect()
                if mq_clnt.isconnected():
                    mqtt_up = True
                    break
            except OSError as e:
                log_errors(f"MQTT Connect error: {e}")
                retry_count += 1  # Kasvata yrityskertojen laskuria
                print(f"MQTT error: {e}, Retry {retry_count}/{max_retries}")

                if retry_count >= max_retries:
                    print("Max retries reached, resetting...")
                    reset()
                else:
                    await asyncio.sleep(5)

    n = 0
    while True:
        await asyncio.sleep(10)
        if deb_scr_a == 1:
            print(f'mqtt-publish test {n}')
        await mq_clnt.publish('result', f'{n}', qos=1)
        n += 1


async def mqtt_pub_l():
    global mqtt_last_update

    async def publish_if_valid(topic, value, min_value, max_value):
        """Helper function to publish if value is within valid range."""
        if min_value < value < max_value:
            await mq_clnt.publish(topic, str(value), retain=0, qos=0)

    while True:
        if not mqtt_up:
            await asyncio.sleep(5)
        elif (time() - mqtt_last_update) >= mqtt_ival:
            await publish_if_valid(t_temp, temp_average, -40, 120)
            await publish_if_valid(t_rh, rh_average, 0, 100)
            await publish_if_valid(t_press, pressure_average, 0, 5000)
            await publish_if_valid(t_gasr, gas_average, 0, 99999999999999)

            if pms.pms_dictionary is not None and (time() - pms.startup_time) > pms.read_interval:
                await publish_if_valid(t_pm1_0, pms.pms_dictionary['PM1_0'], 0, float('inf'))
                await publish_if_valid(t_pm1_0_atm, pms.pms_dictionary['PM1_0_ATM'], 0, float('inf'))
                await publish_if_valid(t_pm2_5, pms.pms_dictionary['PM2_5'], 0, float('inf'))
                await publish_if_valid(t_pm2_5_atm, pms.pms_dictionary['PM2_5_ATM'], 0, float('inf'))
                await publish_if_valid(t_pm10_0, pms.pms_dictionary['PM10_0'], 0, float('inf'))
                await publish_if_valid(t_pm10_0_atm, pms.pms_dictionary['PM10_0_ATM'], 0, float('inf'))
                await publish_if_valid(t_pcnt_0_3, pms.pms_dictionary['PCNT_0_3'], 0, float('inf'))
                await publish_if_valid(t_pcnt_0_5, pms.pms_dictionary['PCNT_0_5'], 0, float('inf'))
                await publish_if_valid(t_pcnt_1_0, pms.pms_dictionary['PCNT_1_0'], 0, float('inf'))
                await publish_if_valid(t_pcnt_2_5, pms.pms_dictionary['PCNT_2_5'], 0, float('inf'))
                await publish_if_valid(t_pcnt_5_0, pms.pms_dictionary['PCNT_5_0'], 0, float('inf'))
                await publish_if_valid(t_pcnt_10_0, pms.pms_dictionary['PCNT_10_0'], 0, float('inf'))

            if aq.aqinndex is not None:
                await publish_if_valid(t_airq, aq.aqinndex, 0, float('inf'))

            if not mhz19_f and co2s.co2_average is not None:
                await publish_if_valid(t_co2, co2s.co2_average, 0, float('inf'))

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


async def update_display_page(content, row, delay):
    """Helper function to update display rows."""
    await display.txt_2_r(content, row, delay)


async def disp_l():
    await display.rot_180(True)

    while True:
        try:
            wdt.feed()  # Feed the watchdog more frequently to avoid resets

            display.inverse = any([
                temp_average is not None and temp_average > temp_thold,
                rh_average is not None and rh_average > rh_thold,
                pressure_average is not None and pressure_average > press_thold,
                gas_average is not None and gas_average > gasr_thold,
                co2s.co2_average is not None and co2s.co2_average > co2_thold,
                aq.aqinndex is not None and aq.aqinndex > aq_thold
            ])

            await update_display_page(f"  {resolve_date()[2]} {resolve_date()[0]}", 0, 5)
            await update_display_page(f"    {resolve_date()[1]}", 1, 5)

            if temp_average is not None and temp_average > 0 and rh_average is not None and rh_average > 0:
                await update_display_page(f"{temp_average:.1f}C Rh:{rh_average:.1f}", 2, 5)
            else:
                await update_display_page("Waiting values", 2, 5)

            if co2s.co2_average is not None and pressure_average is not None and pressure_average > 0:
                await update_display_page(f"CO2:{int(co2s.co2_average)} hPa:{int(pressure_average)}", 3, 5)

            if gas_average is not None and gas_average > 0:
                await update_display_page(f"GasR:{int(gas_average)}", 4, 5)

            if aq.aqinndex is not None:
                await update_display_page(f"AQIndex:{int(aq.aqinndex)}", 5, 5)

            await display.act_scr()
            await asyncio.sleep(1)

            wdt.feed()  # Feed again before starting the next block

            if pms.pms_dictionary is not None:
                await update_display_page("Particles ug/m3", 0, 5)
                await update_display_page(f"PM1.0:{pms.pms_dictionary['PM1_0']} ATM:{pms.pms_dictionary['PM1_0_ATM']}",
                                          2, 5)
                await update_display_page(f"PM2.5:{pms.pms_dictionary['PM2_5']} ATM:{pms.pms_dictionary['PM2_5_ATM']}",
                                          3, 5)
                await update_display_page(
                    f"PM10: {pms.pms_dictionary['PM10_0']} ATM:{pms.pms_dictionary['PM10_0_ATM']}", 4, 5)
                await update_display_page("- ATM for AQI -", 5, 5)
                await display.act_scr()
                await asyncio.sleep(1)

            wdt.feed()

            if deb_scr_a:
                await update_display_page(f"WIFI:   {net.strength}", 0, 5)
                await update_display_page(f"WebRepl:{net.webrepl_started}", 1, 5)
                await update_display_page(f"IP:{net.ip_a}", 2, 5)
                await update_display_page(f"MQTT up:{mqtt_up}", 3, 5)
                await update_display_page(f"Uptime :{broker_uptime}", 4, 5)
                await update_display_page(f"Err:{last_error}", 5, 5)
                await display.act_scr()
                await asyncio.sleep(1)

            if deb_scr_a:
                await update_display_page(f"BMEErrs:{bme_read_errors}", 0, 5)
                await update_display_page(f"PMSErrs:{pms_read_errors}", 1, 5)
                await update_display_page(f"MHZErrs:{mhz_read_errors}", 2, 5)
                await update_display_page(f"Memfree:{gc.mem_free()}", 3, 5)
                await display.act_scr()
                await asyncio.sleep(1)

            wdt.feed()  # Ensure it's called at various stages in the loop

        except Exception as e:
            log_errors(f"Error in display loop: {e}")
            await asyncio.sleep(5)


async def main():
    loop = asyncio.get_event_loop()
    if deb_scr_a == 1:
        loop.create_task(show_what_i_do())
    if start_net == 1:
        loop.create_task(net.net_upd_loop())
    if start_mqtt == 1:
        loop.create_task(mqtt_up_l())
        await asyncio.sleep(1)
        loop.create_task(mqtt_pub_l())
    if mhz19_f is False:
        loop.create_task(co2s.read_co2_loop())
        await asyncio.sleep(1)
    if pms_f is False:
        loop.create_task(pms.read_async_loop())
        await asyncio.sleep(1)
    if pms_f is False:
        loop.create_task(aq.upd_aq_loop())
        await asyncio.sleep(1)
    if bmes_f is False:
        loop.create_task(upd_status_loop())
    loop.create_task(disp_l())
    loop.run_forever()

wdt = WDT(timeout=30000)

if __name__ == "__main__":
    asyncio.run(main())
