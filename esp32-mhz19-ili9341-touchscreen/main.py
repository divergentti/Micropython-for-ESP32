""""
This script is used for airquality measurement.

Display is ILI9341 2.8" TFT touch screen in the SPI bus,
CO2 device is MH-Z19 NDIR-sensor, particle sensor is PMS7003 and temperature/rh/pressure sensor BME280.

Removed comments and refactored variablenames to short version to save memory!

This version is ported for micropython version 1.91.1 which deprecated I2C to SoftI2C.
Added error checking for sensors and display init. Sensor or display error do not stop the code.

Re-organized display class, moved display drawing procedures into main level. Referral using object name (disp).
Added some checkups if user press the screen too early etc.

Updated: 10.10.2022: Jari Hiltunen
"""
from machine import SPI, SoftI2C, Pin, freq, reset, reset_cause
import uasyncio as asyncio
from utime import time, mktime, localtime, sleep
import gc
import network
import drivers.WIFICONN_AS as WifiNet
from drivers.XPT2046 import Touch
from drivers.ILI9341 import Display, color565
from drivers.XGLCD_FONT import XglcdFont
from drivers.AQI import AQI
import drivers.PMS7003_AS as PARTICLES
import drivers.MHZ19B_AS as CO2
import drivers.BME280_float as BmE
gc.collect()
from json import load
import esp
import esp32
from drivers.MQTT_AS import MQTTClient, config
gc.collect()

# Globals
mqtt_up = False
broker_uptime = 0
BME280_sensor_faulty = False
PMS7003_sensor_faulty = False
MHZ19_sensor_faulty = False
screen_faulty = False

try:
    f = open('parameters.py', "r")
    from parameters import CO2_SEN_RX_PIN, CO2_SEN_TX_PIN, CO2_SEN_UART, TFT_CS_PIN, TFT_DC_PIN, \
        TS_MISO_PIN, TS_CS_PIN, TS_IRQ_PIN, TS_MOSI_PIN, TS_SCLK_PIN, TFT_CLK_PIN, \
        TFT_RST_PIN, TFT_MISO_PIN, TFT_MOSI_PIN, TFT_SPI, TS_SPI, \
        P_SEN_UART, P_SEN_TX, P_SEN_RX, I2C_SCL_PIN, I2C_SDA_PIN
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
        TOPIC_AIRQUALITY = data['TOPIC_AIRQUALITY']
        TOPIC_CO2 = data['TOPIC_CO2']
        TOPIC_PM1_0 = data['TOPIC_PM1_0']
        TOPIC_PM1_0_ATM = data['TOPIC_PM1_0_ATM']
        TOPIC_PM2_5 = data['TOPIC_PM2_5']
        TOPIC_PM2_5_ATM = data['TOPIC_PM2_5_ATM']
        TOPIC_PM10_0 = data['TOPIC_PM10_0']
        TOPIC_PM10_0_ATM = data['TOPIC_PM10_0_ATM']
        TOPIC_PCNT_0_3 = data['TOPIC_PCNT_0_3']
        TOPIC_PCNT_0_5 = data['TOPIC_PCNT_0_5']
        TOPIC_PCNT_1_0 = data['TOPIC_PCNT_1_0']
        TOPIC_PCNT_2_5 = data['TOPIC_PCNT_2_5']
        TOPIC_PCNT_5_0 = data['TOPIC_PCNT_5_0']
        TOPIC_PCNT_10_0 = data['TOPIC_PCNT_10_0']
        CO2_ALM_THOLD = data['CO2_ALARM_TRESHOLD']
        AQ_THOLD = data['AIRQUALIY_TRESHOLD']
        TEMP_THOLD = data['TEMP_TRESHOLD']
        TEMP_CORRECTION = data['TEMP_CORRECTION']
        RH_THOLD = data['RH_TRESHOLD']
        RH_CORRECTION = data['RH_CORRECTION']
        P_THOLD = data['PRESSURE_TRESHOLD']
        PRESSURE_CORRECTION = data['PRESSURE_CORRECTION']

except OSError:
    print("Runtime parameters missing. Can not continue!")
    sleep(30)
    raise


def resolve_date():
    # For Finland
    (year, month, mdate, hour, minute, second, wday, yday) = localtime()
    weekdays = ['Ma', 'Ti', 'Ke', 'To', 'Pe', 'La', 'Su']
    summer_march = mktime((year, 3, (14 - (int(5 * year / 4 + 1)) % 7), 1, 0, 0, 0, 0, 0))
    winter_december = mktime((year, 10, (7 - (int(5 * year / 4 + 1)) % 7), 1, 0, 0, 0, 0, 0))
    if mktime(localtime()) < summer_march:
        dst = localtime(mktime(localtime()) + 7200)
    elif mktime(localtime()) < winter_december:
        dst = localtime(mktime(localtime()) + 7200)
    else:
        dst = localtime(mktime(localtime()) + 10800)
    (year, month, mdate, hour, minute, second, wday, yday) = dst
    day = "%s.%s.%s" % (mdate, month, year)
    time = "%s:%s:%s" % ("{:02d}".format(hour), "{:02d}".format(minute), "{:02d}".format(second))
    return day, time, weekdays[wday]


class TFTDisplay(object):

    def __init__(self, touchspi, dispspi):

        # Display - some digitizers may be rotated 270 degrees!
        self.d = Display(spi=dispspi, cs=Pin(TFT_CS_PIN), dc=Pin(TFT_DC_PIN), rst=Pin(TFT_RST_PIN),
                         width=320, height=240, rotation=90)
        self.unispace = XglcdFont('fonts/Unispace12x24.c', 12, 24)
        self.a_font = self.unispace
        self.cols = {'red': color565(255, 0, 0), 'green': color565(0, 255, 0), 'blue': color565(0, 0, 255),
                     'yellow': color565(255, 255, 0), 'fuschia': color565(255, 0, 255),
                     'aqua': color565(0, 255, 255), 'maroon': color565(128, 0, 0),
                     'darkgreen': color565(0, 128, 0), 'navy': color565(0, 0, 128),
                     'teal': color565(0, 128, 128), 'purple': color565(128, 0, 128),
                     'olive': color565(128, 128, 0), 'orange': color565(255, 128, 0),
                     'deep_pink': color565(255, 0, 128), 'charteuse': color565(128, 255, 0),
                     'spring_green': color565(0, 255, 128), 'indigo': color565(128, 0, 255),
                     'dodger_blue': color565(0, 128, 255), 'cyan': color565(128, 255, 255),
                     'pink': color565(255, 128, 255), 'light_yellow': color565(255, 255, 128),
                     'light_coral': color565(255, 128, 128), 'light_green': color565(128, 255, 128),
                     'white': color565(255, 255, 255), 'black': color565(0, 0, 0)}
        self.c_fnts = 'white'
        self.col_bckg = 'light_green'
        self.xpt = Touch(spi=touchspi, cs=Pin(TS_CS_PIN), int_pin=Pin(TS_IRQ_PIN),
                         width=240, height=320, x_min=100, x_max=1962, y_min=100, y_max=1900)
        self.xpt.int_handler = self.first_touch
        self.t_tched = False
        self.scr_actv_time = None
        self.r_num = 1
        self.r_h = 10
        self.f_h = 10
        self.f_w = 10
        self.max_r = self.d.height / self.f_h
        self.indent_p = 12
        self.scr_tout = SCREEN_TIMEOUT
        self.d_all_ok = True
        self.scr_upd_ival = SCREEN_UPDATE_INTERVAL
        self.d_scr_active = False
        self.rw_col = None
        self.rows = None
        self.dtl_scr_sel = None

    def first_touch(self, x, y):
        if DEBUG_SCREEN_ACTIVE == 1:
            print("Touched!")
        self.t_tched = True


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


async def upd_status_loop():
    while True:
        # For network
        if net.net_ok is True:
            net.use_ssid = network.WLAN(network.STA_IF).config('essid')
            net.ip_a = network.WLAN(network.STA_IF).ifconfig()[0]
            net.strength = network.WLAN(network.STA_IF).status('rssi')

        # For sensors thresholds, background change
        disp.d_all_ok = True
        if not MHZ19_sensor_faulty:
            if co2s.co2_average is not None:
                if co2s.co2_average > CO2_ALM_THOLD:
                    disp.d_all_ok = False
        if aq.aqinndex is not None:
            if aq.aqinndex > AQ_THOLD:
                disp.d_all_ok = False
        if not BME280_sensor_faulty:
            if bmes.values[0] is not None:
                if float(bmes.values[0][:-1]) > TEMP_THOLD:
                    disp.d_all_ok = False
            if bmes.values[2] is not None:
                if float(bmes.values[2][:-1]) > RH_THOLD:
                    disp.d_all_ok = False
            if bmes.values[1] is not None:
                if float(bmes.values[1][:-3]) > P_THOLD:
                    disp.d_all_ok = False
        gc.collect()
        await asyncio.sleep(disp.scr_upd_ival - 2)


async def show_what_i_do():
    # Output is REPL

    while True:
        if START_NETWORK == 1:
            print("WiFi Connected %s" % net.net_ok)
            print("WiFi failed connects %s" % net.con_att_fail)
            print("Signal strength %s" % net.strength)
        if START_MQTT == 1:
            print("MQTT Connected %s" % mqtt_up)
            print("MQTT broker uptime %s" % broker_uptime)
        print("Memory free: %s" % gc.mem_free())
        print("Memory alloc: %s" % gc.mem_alloc())
        print("Toucscreen pressed: %s" % disp.t_tched)
        print("Details screen active: %s" % disp.d_scr_active)
        print("-------")
        if BME280_sensor_faulty:
            print("BME280 sensor faulty!")
        if MHZ19_sensor_faulty:
            print("MHZ19 sensor faulty!")
        if PMS7003_sensor_faulty:
            print("PMS7003 sensor faulty!")
        if screen_faulty:
            print("Screen faulty!")
        await asyncio.sleep(5)

# Kick in some speed, max 240000000, normal 160000000, min with WiFi 80000000
freq(240000000)

# Network handshake
net = WifiNet.ConnectWiFi(SSID1, PASSWORD1, SSID2, PASSWORD2, NTPSERVER, DHCP_NAME, START_WEBREPL, WEBREPL_PASSWORD)

# Particle sensor
try:
    pms = PARTICLES.PSensorPMS7003(uart=P_SEN_UART, rxpin=P_SEN_RX, txpin=P_SEN_TX)
except OSError as e:
    print("Error: %s - Particle sensor init error!" % e)
    PMS7003_sensor_faulty = True
# Air Quality calculations
aq = AirQuality(pms)

# CO2 sensor
try:
    co2s = CO2.MHZ19bCO2(uart=CO2_SEN_UART, rxpin=CO2_SEN_RX_PIN, txpin=CO2_SEN_TX_PIN)
except OSError as e:
    print("Error: %s - MHZ19 sensor init error!" % e)
    MHZ19_sensor_faulty = True

# BME280 sensor
i2c = SoftI2C(scl=Pin(I2C_SCL_PIN), sda=Pin(I2C_SDA_PIN))
try:
    bmes = BmE.BME280(i2c=i2c)
except OSError as e:
    print("Error: %s - BME sensor init error!" % e)
    BME280_sensor_faulty = True

#  If you use UART2, you have to delete co2 object and re-create it after power on boot!
#  This may be fixed in new versions
if reset_cause() == 1:
    del co2s
    sleep(5)   # 2 is not enough!
    co2s = CO2.MHZ19bCO2(uart=CO2_SEN_UART, rxpin=CO2_SEN_RX_PIN, txpin=CO2_SEN_TX_PIN)
#  Touchscreen and display init
t_spi = SPI(TS_SPI)  # HSPI
t_spi.init(baudrate=1100000, sck=Pin(TS_SCLK_PIN), mosi=Pin(TS_MOSI_PIN), miso=Pin(TS_MISO_PIN))
d_spi = SPI(TFT_SPI)  # VSPI - baudrate 40 - 90 MHz appears to be working, screen update still slow
d_spi.init(baudrate=50000000, sck=Pin(TFT_CLK_PIN), mosi=Pin(TFT_MOSI_PIN), miso=Pin(TFT_MISO_PIN))
try:
    disp = TFTDisplay(t_spi, d_spi)
except OSError as e:
    print("Error: %s - Touchscreen or display init error!" % e)
    screen_faulty = True


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
        await client.connect()
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


async def details_screen_loop():
    disp.scr_actv_time = time()
    if not screen_faulty and not PMS7003_sensor_faulty:
        r, r_c = await particle_screen()
        disp.d_scr_active = True
        try:
            await show_screen(r, r_c)
        except TypeError:
            pass
        await asyncio.sleep(SCREEN_UPDATE_INTERVAL)
    if not screen_faulty and not BME280_sensor_faulty:
        r, r_c = await sensor_monitor()
        try:
            await show_screen(r, r_c)
        except TypeError:
            pass
        await asyncio.sleep(SCREEN_UPDATE_INTERVAL)
    if not screen_faulty:
        r, r_c = await sys_monitor()
        try:
            await show_screen(r, r_c)
        except TypeError:
            pass
        await asyncio.sleep(SCREEN_UPDATE_INTERVAL)
    if not screen_faulty:
        r, r_c = await net_monitor()
        try:
            await show_screen(r, r_c)
        except TypeError:
            pass
        await asyncio.sleep(SCREEN_UPDATE_INTERVAL)
    disp.d_scr_active = False
    disp.t_tched = False


async def rot_scr():
    disp.scr_actv_time = time()
    disp.d_scr_active = True
    r, r_c = await particle_screen()
    if not r is None:
        try:
            await show_screen(r, r_c)
        except TypeError:
            pass
    await asyncio.sleep(SCREEN_UPDATE_INTERVAL)
    r, r_c = await sensor_monitor()
    if not r is None:
        try:
            await show_screen(r, r_c)
        except TypeError:
            pass
    await asyncio.sleep(SCREEN_UPDATE_INTERVAL)
    r, r_c = await sys_monitor()
    if not r is None:
        try:
            await show_screen(r, r_c)
        except TypeError:
            pass
    await asyncio.sleep(SCREEN_UPDATE_INTERVAL)
    r, r_c = await net_monitor()
    if not r is None:
        try:
            await show_screen(r, r_c)
        except TypeError:
            pass
    await asyncio.sleep(SCREEN_UPDATE_INTERVAL)
    disp.d_scr_active = False
    disp.t_tched = False


async def update_screen_loop():
    while True:
        if disp.t_tched is True:
            if disp.d_scr_active is False:
                try:
                    await rot_scr()
                except TypeError:
                    await error_bckg()
                    disp.d.draw_text(disp.indent_p, 25 + disp.r_h * 2, "Please, wait!", disp.a_font, disp.cols["white"],
                                     disp.cols[disp.col_bckg])
                    disp.d.draw_text(disp.indent_p, 25 + disp.r_h * 3, "Sensors not ready!", disp.a_font, disp.cols["white"],
                                     disp.cols[disp.col_bckg])
                    disp.d.draw_text(disp.indent_p, 25 + disp.r_h * 4, "Thank you!", disp.a_font, disp.cols["white"],
                                     disp.cols[disp.col_bckg])
                    pass
            elif (disp.d_scr_active is True) and ((time() - disp.scr_actv_time) > disp.scr_tout):
                # Timeout
                disp.d_scr_active = False
                disp.t_tched = False
        else:
            r, r_c = await upd_welcome()
            await show_screen(r, r_c)


async def wait_timer():
    n = 0
    while (disp.t_tched is False) and (n <= disp.scr_upd_ival * 1000):
        await asyncio.sleep_ms(1)
        n += 1


async def show_screen(rows, row_colours):
    r1 = "Airquality v1.0"
    r1_c = 'red'
    r2 = "Starting"
    r2_c = 'white'
    r3 = "Wait"
    r3_c = 'red'
    r4 = "for"
    r4_c = 'red'
    r5 = "init"
    r5_c = 'red'
    r6 = "and"
    r6_c = 'red'
    r7 = "values."
    r7_c = 'red'
    disp.f_h = disp.a_font.height
    disp.r_h = disp.f_h + 2  # 2 pixel space between rows
    if rows is not None:
        if len(rows) == 7:
            r1, r2, r3, r4, r5, r6, r7 = rows
        if len(row_colours) == 7:
            r1_c, r2_c, r3_c, r4_c, r5_c, r6_c, r7_c = row_colours
    # strip too long lines!
    max_c = int((disp.d.width - 20) / disp.a_font.width)
    r1 = r1[:max_c]
    r2 = r2[:max_c]
    r3 = r3[:max_c]
    r4 = r4[:max_c]
    r5 = r5[:max_c]
    r6 = r6[:max_c]
    r7 = r7[:max_c]
    if disp.d_all_ok is True:
        await ok_bckg()
    else:
        await error_bckg()
    disp.d.draw_text(disp.indent_p, 25, r1, disp.a_font, disp.cols[r1_c], disp.cols[disp.col_bckg])
    disp.d.draw_text(disp.indent_p, 25 + disp.r_h, r2, disp.a_font, disp.cols[r2_c], disp.cols[disp.col_bckg])
    disp.d.draw_text(disp.indent_p, 25 + disp.r_h * 2, r3, disp.a_font, disp.cols[r3_c], disp.cols[disp.col_bckg])
    disp.d.draw_text(disp.indent_p, 25 + disp.r_h * 3, r4, disp.a_font, disp.cols[r4_c], disp.cols[disp.col_bckg])
    disp.d.draw_text(disp.indent_p, 25 + disp.r_h * 4, r5, disp.a_font, disp.cols[r5_c], disp.cols[disp.col_bckg])
    disp.d.draw_text(disp.indent_p, 25 + disp.r_h * 5, r6, disp.a_font, disp.cols[r6_c], disp.cols[disp.col_bckg])
    disp.d.draw_text(disp.indent_p, 25 + disp.r_h * 6, r7, disp.a_font, disp.cols[r7_c], disp.cols[disp.col_bckg])
    gc.collect()
    await wait_timer()


async def ok_bckg():
    disp.d.fill_rectangle(0, 0, disp.d.width, disp.d.height, disp.cols['yellow'])
    disp.d.fill_rectangle(10, 10, disp.d.width - 20, disp.d.height - 20, disp.cols['light_green'])
    disp.col_bckg = 'light_green'


async def error_bckg():
    disp.d.fill_rectangle(0, 0, disp.d.width, disp.d.height, disp.cols['red'])
    disp.d.fill_rectangle(10, 10, disp.d.width - 20, disp.d.height - 20, disp.cols['light_green'])
    disp.col_bckg = 'light_green'


async def upd_welcome():
    r1 = "%s %s %s" % (resolve_date()[2], resolve_date()[0], resolve_date()[1])
    # r1 = "Ilmanlaatu (C) J.Hiltunen"
    r1_c = 'black'
    if co2s.co2_value is None:
        r2 = "CO2: waiting..."
        r2_c = 'yellow'
    elif co2s.co2_average is None:
        r2 = "CO2 average counting..."
        r2_c = 'yellow'
    else:
        r2 = "CO2: %s ppm (%s)" % ("{:.1f}".format(co2s.co2_value), "{:.1f}".format(co2s.co2_average))
        if (co2s.co2_average > CO2_ALM_THOLD) or (co2s.co2_value > CO2_ALM_THOLD):
            r2_c = 'red'
        else:
            r2_c = 'blue'
    if aq.aqinndex is None:
        r3 = "AirQuality not ready"
        r3_c = 'yellow'
    else:
        r3 = "Ilmanlaatuindeksi: %s" % ("{:.1f}".format(aq.aqinndex))
        if aq.aqinndex > AQ_THOLD:
            r3_c = 'red'
        else:
            r3_c = 'blue'
    if bmes.values[0] is None:
        r4 = "Waiting values..."
        r4_c = 'yellow'
    else:
        r4 = "Lampo: %s (DP: %sC)" % (bmes.values[0], "{:.1f}".format(bmes.dew_point))
        if float(bmes.values[0][:-1]) > TEMP_THOLD:
            r4_c = 'red'
        else:
            r4_c = 'blue'
    if bmes.values[2] is None:
        r5 = "Waiting values..."
        r5_c = 'yellow'
    else:
        r5 = "Kosteus: %s (%sM)" % (bmes.values[2], "{:.1f}".format(bmes.altitude))
        if float(bmes.values[2][:-1]) > RH_THOLD:
            r5_c = 'red'
        else:
            r5_c = 'blue'
    if bmes.values[1] is None:
        r6 = "Waiting values..."
        r6_c = 'yellow'
    else:
        r6 = "Paine: %s ATM" % bmes.values[1]
        if float(bmes.values[1][:-3]) > P_THOLD:
            r6_c = 'red'
        else:
            r6_c = 'blue'
    if aq.aqinndex is None:  # no detail offering prior to AQ values
        r7 = " "
    else:
        r7 = "Koskettamalla datat"
    r7_c = 'white'
    rows = r1, r2, r3, r4, r5, r6, r7
    row_colours = r1_c, r2_c, r3_c, r4_c, r5_c, r6_c, r7_c
    return rows, row_colours


async def particle_screen():
    if (pms.pms_dictionary is not None) and ((time() - pms.startup_time) > pms.read_interval):
        r1 = "1. Konsentraatio ug/m3:"
        r1_c = 'blue'
        if (pms.pms_dictionary['PM1_0'] is not None) and (pms.pms_dictionary['PM1_0_ATM'] is not None) and \
                    (pms.pms_dictionary['PM2_5'] is not None) and (pms.pms_dictionary['PM2_5_ATM'] is not None):
            r2 = " PM1:%s (%s) PM2.5:%s (%s)" % (pms.pms_dictionary['PM1_0'], pms.pms_dictionary['PM1_0_ATM'],
                                                pms.pms_dictionary['PM2_5'], pms.pms_dictionary['PM2_5_ATM'])
            r2_c = 'black'
        else:
            r2 = " Waiting"
            r2_c = 'yellow'
        if (pms.pms_dictionary['PM10_0'] is not None) and (pms.pms_dictionary['PM10_0_ATM'] is not None):
            r3 = " PM10: %s (ATM: %s)" % (pms.pms_dictionary['PM10_0'], pms.pms_dictionary['PM10_0_ATM'])
            r3_c = 'black'
        else:
            r3 = "Waiting"
            r3_c = 'yellow'
        r4 = "2. Partikkelit/1L/um:"
        r4_c = 'blue'
        if (pms.pms_dictionary['PCNT_0_3'] is not None) and (pms.pms_dictionary['PCNT_0_5'] is not None):
            r5 = " %s < 0.3 & %s <0.5 " % (pms.pms_dictionary['PCNT_0_3'], pms.pms_dictionary['PCNT_0_5'])
            r5_c = 'navy'
        else:
            r5 = " Waiting"
            r5_c = 'yellow'
        if (pms.pms_dictionary['PCNT_1_0'] is not None) and (pms.pms_dictionary['PCNT_2_5'] is not None):
            r6 = " %s < 1.0 & %s < 2.5" % (pms.pms_dictionary['PCNT_1_0'], pms.pms_dictionary['PCNT_2_5'])
            r6_c = 'navy'
        else:
            r6 = "Waiting"
            r6_c = 'yellow'
        if (pms.pms_dictionary['PCNT_5_0'] is not None) and (pms.pms_dictionary['PCNT_10_0'] is not None):
            r7 = " %s < 5.0 & %s < 10.0" % (pms.pms_dictionary['PCNT_5_0'], pms.pms_dictionary['PCNT_10_0'])
            r7_c = 'navy'
        else:
            r7 = " Waiting"
            r7_c = 'yellow'
        rows = r1, r2, r3, r4, r5, r6, r7
        row_colours = r1_c, r2_c, r3_c, r4_c, r5_c, r6_c, r7_c
        return rows, row_colours
    else:
        return None


async def sensor_monitor():
    if not BME280_sensor_faulty and not PMS7003_sensor_faulty and not MHZ19_sensor_faulty:
        row1 = "3. Sensoridata"
        row1_colour = 'black'
        row2 = "MHZ19B CRC errors: %s " % co2s.crc_errors
        row2_colour = 'blue'
        row3 = "MHZ19B Range errors: %s" % co2s.range_errors
        row3_colour = 'blue'
        row4 = "PMS7003 version %s" % pms.pms_dictionary['VERSION']
        row4_colour = 'blue'
        row5 = "BME280 address %s" % bmes.address
        row5_colour = 'blue'
        row6 = "BME280 sealevel %s" % bmes.sealevel
        row6_colour = 'blue'
        row7 = " Free row "
        row7_colour = 'light_green'
        rows = row1, row2, row3, row4, row5, row6, row7
        row_colours = row1_colour, row2_colour, row3_colour, row4_colour, row5_colour, row6_colour, row7_colour
        return rows, row_colours
    else:
        return None


async def sys_monitor():
    row1 = "4. System monitor"
    row1_colour = 'black'
    row2 = "Uptime: %s" % (time() - net.startup_time)
    row2_colour = 'blue'
    row3 = "Mem free: %s" % gc.mem_free()
    row3_colour = 'blue'
    row4 = "Mem allocated: %s" % gc.mem_alloc()
    row4_colour = 'blue'
    row5 = "Flash size: %s " % esp.flash_size()
    row5_colour = 'blue'
    row6 = "MCU Temp: %sC" % ("{:.1f}".format(((float(esp32.raw_temperature())-32.0) * 5/9)))
    row6_colour = 'blue'
    row7 = "Hall sensor %s" % esp32.hall_sensor()
    row7_colour = 'blue'
    rows = row1, row2, row3, row4, row5, row6, row7
    row_colours = row1_colour, row2_colour, row3_colour, row4_colour, row5_colour, row6_colour, row7_colour
    return rows, row_colours


async def net_monitor():
    if START_NETWORK == 1:
        row1 = "5. Network monitor"
        row1_colour = 'black'
        row2 = "WiFi IP: %s" % net.ip_a
        row2_colour = 'blue'
        row3 = "WiFi AP: %s" % net.use_ssid
        row3_colour = 'blue'
        row4 = "WiFi Strength: %s" % net.strength
        row4_colour = 'blue'
        row5 = "WiFi fail: %s" % net.con_att_fail
        row5_colour = 'blue'
        row6 = "MQTT Up: %s" % mqtt_up
        row6_colour = 'blue'
        if broker_uptime is not 0:
            row7 = "Broker up %s" % broker_uptime[:-8]
        else:
            row7 = "Broker down"
        row7_colour = 'blue'
        rows = row1, row2, row3, row4, row5, row6, row7
        row_colours = row1_colour, row2_colour, row3_colour, row4_colour, row5_colour, row6_colour, row7_colour
        return rows, row_colours
    else:
        return None


async def mqtt_publish_loop():
    while True:
        if mqtt_up is False:
            await asyncio.sleep(10)
        else:
            await asyncio.sleep(MQTT_INTERVAL)
            if not PMS7003_sensor_faulty:
                if (pms.pms_dictionary is not None) and ((time() - pms.startup_time) > pms.read_interval):
                    if pms.pms_dictionary['PM1_0'] is not None:
                        await client.publish(TOPIC_PM1_0, str(pms.pms_dictionary['PM1_0']), retain=0, qos=0)
                    if pms.pms_dictionary['PM1_0_ATM'] is not None:
                        await client.publish(TOPIC_PM1_0_ATM, str(pms.pms_dictionary['PM1_0_ATM']), retain=0, qos=0)
                    if pms.pms_dictionary['PM2_5'] is not None:
                        await client.publish(TOPIC_PM2_5, str(pms.pms_dictionary['PM2_5']), retain=0, qos=0)
                    if pms.pms_dictionary['PM2_5_ATM'] is not None:
                        await client.publish(TOPIC_PM2_5_ATM, str(pms.pms_dictionary['PM2_5_ATM']), retain=0, qos=0)
                    if pms.pms_dictionary['PM10_0'] is not None:
                        await client.publish(TOPIC_PM10_0, str(pms.pms_dictionary['PM10_0']), retain=0, qos=0)
                    if pms.pms_dictionary['PM10_0_ATM'] is not None:
                        await client.publish(TOPIC_PM10_0_ATM, str(pms.pms_dictionary['PM10_0_ATM']), retain=0, qos=0)
                    if pms.pms_dictionary['PCNT_0_3'] is not None:
                        await client.publish(TOPIC_PCNT_0_3, str(pms.pms_dictionary['PCNT_0_3']), retain=0, qos=0)
                    if pms.pms_dictionary['PCNT_0_5'] is not None:
                        await client.publish(TOPIC_PCNT_0_5, str(pms.pms_dictionary['PCNT_0_5']), retain=0, qos=0)
                    if pms.pms_dictionary['PCNT_1_0'] is not None:
                        await client.publish(TOPIC_PCNT_1_0, str(pms.pms_dictionary['PCNT_1_0']), retain=0, qos=0)
                    if pms.pms_dictionary['PCNT_2_5'] is not None:
                        await client.publish(TOPIC_PCNT_2_5, str(pms.pms_dictionary['PCNT_2_5']), retain=0, qos=0)
                    if pms.pms_dictionary['PCNT_5_0'] is not None:
                        await client.publish(TOPIC_PCNT_5_0, str(pms.pms_dictionary['PCNT_5_0']), retain=0, qos=0)
                    if pms.pms_dictionary['PCNT_10_0'] is not None:
                        await client.publish(TOPIC_PCNT_10_0, str(pms.pms_dictionary['PCNT_10_0']), retain=0, qos=0)
            if not BME280_sensor_faulty:
                if bmes.values[0][:-1] is not None:
                    await client.publish(TOPIC_TEMP, bmes.values[0][:-1], retain=0, qos=0)
                if bmes.values[2][:-1] is not None:
                    await client.publish(TOPIC_RH, bmes.values[2][:-1], retain=0, qos=0)
                if bmes.values[1][:-3] is not None:
                    await client.publish(TOPIC_PRESSURE, bmes.values[1][:-3], retain=0, qos=0)
                if aq.aqinndex is not None:
                    await client.publish(TOPIC_AIRQUALITY, str(aq.aqinndex), retain=0, qos=0)
            if not MHZ19_sensor_faulty:
                if co2s.co2_average is not None:
                    await client.publish(TOPIC_CO2, str(co2s.co2_average), retain=0, qos=0)

# For MQTT_AS
config['server'] = MQTT_SERVER
config['user'] = MQTT_USER
config['password'] = MQTT_PASSWORD
config['port'] = MQTT_PORT
config['client_id'] = CLIENT_ID
config['ssl'] = False
client = MQTTClient(config)


async def main():
    loop = asyncio.get_event_loop()
    if START_NETWORK == 1:
        loop.create_task(net.net_upd_loop())
    loop.create_task(pms.read_async_loop())
    loop.create_task(co2s.read_co2_loop())
    loop.create_task(aq.upd_aq_loop())
    loop.create_task(upd_status_loop())
    if DEBUG_SCREEN_ACTIVE == 1:
        loop.create_task(show_what_i_do())
    if START_MQTT == 1:
        loop.create_task(mqtt_up_loop())
        loop.create_task(mqtt_publish_loop())
    loop.create_task(update_screen_loop())
    loop.run_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except MemoryError:
        reset()
