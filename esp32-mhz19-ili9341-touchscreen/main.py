""""
This script is used for air quality measurement.

Display is ILI9341 2.8" TFT touch screen in the SPI bus,
CO2 device is MH-Z19 NDIR-sensor, particle sensor is PMS7003 and temperature/rh/pressure sensor is BME280.
Backlight control is done with 2 transistors, PNP and NPN (small TO-92 are ok).
Partly asynchronous. Due to memory leakage MQTT_AS.py is not used!

Updated: 8.6.2023: Jari Hiltunen
"""
from machine import SPI, SoftI2C, Pin, freq, reset, reset_cause
import uasyncio as asyncio
from utime import time, mktime, localtime, sleep
from drivers.XPT2046 import Touch
from drivers.ILI9341 import Display, color565
from drivers.XGLCD_FONT import XglcdFont
import gc
gc.collect()
gc.threshold(gc.mem_free() // 4 + gc.mem_alloc())
from drivers.SIMPLE import MQTTClient
import network
from drivers.AQI import AQI
import drivers.PMS7003_AS as PARTICLES
import drivers.MHZ19B_AS as CO2
import drivers.BME280_float as BmE
gc.collect()
gc.threshold(gc.mem_free() // 4 + gc.mem_alloc())
from json import load
import esp
import esp32
import drivers.WIFICONN_AS as WIFINET
b_upt = 0
BME280_f = False
temp_avg = None
rh_avg = None
press_avg = None
PMS7003_f = False
MHZ19_f = False
scr_f = False
last_update =  time()

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
    from parameters import CO2_SEN_RX_PIN, CO2_SEN_TX_PIN, CO2_SEN_UART, TFT_CS_PIN, TFT_DC_PIN, \
        TS_MISO_PIN, TS_CS_PIN, TS_IRQ_PIN, TS_MOSI_PIN, TS_SCLK_PIN, TFT_CLK_PIN, \
        TFT_RST_PIN, TFT_MISO_PIN, TFT_MOSI_PIN, TFT_SPI, TS_SPI, \
        P_SEN_UART, P_SEN_TX, P_SEN_RX, I2C_SCL_PIN, I2C_SDA_PIN, BACKLIGHT_PIN
    f.close()
except OSError as e:  # open failed
    log_errors("Error: %s - parameter.py-file missing! Can not continue!" % e)
    raise ValueError("Error: %s - parameter.py-file missing! Can not continue!" % e)

try:
    f = open('runtimeconfig.json', 'r')
    with open('runtimeconfig.json') as config_file:
        data = load(config_file)
        f.close()
        S1 = data['S1']
        P1 = data['P1']
        S2 = data['S2']
        P2 = data['P2']
        MQSRV = data['MQSRV']
        MQPW = data['MQPW']
        MQUSR = data['MQUSR']
        MQP = data['MQP']
        MQSL = data['MQSL']
        MQIVAL = data['MQIVAL']
        CLID = data['CLID']
        T_ERR = data['T_ERR']
        WBRPLPW = data['WBRPLPW']
        NTPS = data['NTPS']
        DHCPN = data['DHCPN']
        SWEBR = data['SWEBR']
        SNET = data['SNET']
        SMQTT = data['SMQTT']
        S_UPDE_IVAL = data['S_UPDE_IVAL']
        DEBUG = data['DEBUG']
        S_TOUT = data['S_TOUT']
        BLIGHT_TOUT = data['BLIGHT_TOUT']
        T_TEMP = data['T_TEMP']
        T_RH = data['T_RH']
        T_PRESS = data['T_PRESS']
        T_AIRQ = data['T_AIRQ']
        T_CO2 = data['T_CO2']
        T_PM1_0 = data['T_PM1_0']
        T_PM1_0_ATM = data['T_PM1_0_ATM']
        T_PM2_5 = data['T_PM2_5']
        T_PM2_5_ATM = data['T_PM2_5_ATM']
        T_PM10_0 = data['T_PM10_0']
        T_PM10_0_ATM = data['T_PM10_0_ATM']
        T_PCNT_0_3 = data['T_PCNT_0_3']
        T_PCNT_0_5 = data['T_PCNT_0_5']
        T_PCNT_1_0 = data['T_PCNT_1_0']
        T_PCNT_2_5 = data['T_PCNT_2_5']
        T_PCNT_5_0 = data['T_PCNT_5_0']
        T_PCNT_10_0 = data['T_PCNT_10_0']
        CO2_THOLD = data['CO2_THOLD']
        AQ_THOLD = data['AQ_THOLD']
        TEMP_THOLD = data['TEMP_THOLD']
        TEMP_COR = data['TEMP_COR']
        RH_THOLD = data['RH_THOLD']
        RH_COR = data['RH_COR']
        PRESS_THOLD = data['PRESS_THOLD']
        PRESS_COR = data['PRESS_COR']
except OSError as e:
    log_errors("Error %s: Runtime parameters missing. Can not continue!" % e)
    raise ValueError("Error %s: Runtime parameters missing. Can not continue!" % e)


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
        "begin": (3, 6, 2, 3),
            # 3 = March, 2 = last, 6 = Sunday, 3 = 03:00
        "end": (10, 6, 2, 4),   # DST end  month, day, 1=first, 2=last at 04:00.
            # 10 = October, 2 = last, 6 = Sunday, 4 = 04:00
        "timezone": 2,          # hours from UTC during normal (winter time)
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


class TFTDisplay(object):
    def __init__(self, touchspi, dispspi):
        # Display - some digitizers may be rotated 270 degrees!
        self.d = Display(spi=dispspi, cs=Pin(TFT_CS_PIN), dc=Pin(TFT_DC_PIN), rst=Pin(TFT_RST_PIN),
                         width=320, height=240, rotation=90)
        self.unispace = XglcdFont('fonts/Unispace12x24.c', 12, 24)
        self.a_font = self.unispace
        self.cols = {'red': color565(255, 0, 0), 'green': color565(0, 255, 0), 'blue': color565(0, 0, 255),
                     'yellow': color565(255, 255, 0), 'light_green': color565(128, 255, 128),
                     'white': color565(255, 255, 255), 'navy': color565(0, 0, 128), 'black': color565(0, 0, 0)}
        self.c_fnts = 'white'
        self.col_bckg = 'light_green'
        self.xpt = Touch(spi=touchspi, cs=Pin(TS_CS_PIN), int_pin=Pin(TS_IRQ_PIN),
                         width=240, height=320, x_min=100, x_max=1962, y_min=100, y_max=1900)
        self.xpt.int_handler = self.first_touch
        # Backlight control
        self.backlight = Pin(BACKLIGHT_PIN, Pin.OUT)
        self.t_tched = False
        self.scr_actv_time = None
        self.r_num = 1
        self.r_h = 10
        self.f_h = 10
        self.f_w = 10
        self.max_r = self.d.height / self.f_h
        self.indent_p = 12
        self.scr_tout = S_TOUT
        self.d_all_ok = True
        self.scr_upd_ival = S_UPDE_IVAL
        self.d_scr_active = False
        self.rw_col = None
        self.rows = None
        self.dtl_scr_sel = None
        self.backlight_status = True

    def first_touch(self, x, y):
        self.t_tched = True

    def backlight_on(self):
        self.backlight.off()
        self.backlight_status = True

    def backlight_off(self):
        self.backlight.on()
        self.backlight_status = False


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
    global temp_avg, rh_avg, press_avg
    pres_list = []
    temp_list = []
    rh_list = []
    while True:
        disp.d_all_ok = True
        if not MHZ19_f:
            if co2s.co2_average is not None:
                if co2s.co2_average > CO2_THOLD:
                    disp.d_all_ok = False
        if aq.aqinndex is not None:
            if aq.aqinndex > AQ_THOLD:
                disp.d_all_ok = False
        if not BME280_f:
            if bmes.values[0] is not None:
                temp_list.append(round(float(bmes.values[0][:-1]), 1) + TEMP_COR)
            if bmes.values[2] is not None:
                rh_list.append(round(float(bmes.values[2][:-1]), 1) + RH_COR)
            if bmes.values[1] is not None:
                pres_list.append(round(float(bmes.values[1][:-3]), 1) + PRESS_COR)
            if len(temp_list) >= 20:
                temp_list.pop(0)
            if len(rh_list) >= 20:
                rh_list.pop(0)
            if len(pres_list) >= 20:
                pres_list.pop(0)
            if len(temp_list) > 1:
                temp_avg = round(sum(temp_list) / len(temp_list), 1)
            if len(rh_list) > 1:
                rh_avg = round(sum(rh_list) / len(rh_list), 1)
            if len(pres_list) > 1:
                press_avg = round(sum(pres_list) / len(pres_list), 1)
            if (temp_avg is not None) and (rh_avg is not None) and (press_avg is not None):
                if (temp_avg > TEMP_THOLD) or (rh_avg > RH_THOLD) or (press_avg > PRESS_THOLD):
                    disp.d_all_ok = False
        gc.collect()
        gc.threshold(gc.mem_free() // 4 + gc.mem_alloc())
        await asyncio.sleep(disp.scr_upd_ival - 2)


async def show_what_i_do():
    while True:
        print("\n1 ---------WIFI------------- 1")
        if SNET == 1:
            print("   WiFi Connected %s, signal strength: %s" % (net.net_ok, net.strength))
            print("   IP-address: %s" % net.ip_a)
        print("   Memory free: %s, allocated: %s" % (gc.mem_free(), gc.mem_alloc()))
        print("   Heap info %s, hall sensor %s, raw-temp %sC" % (esp32.idf_heap_info(esp32.HEAP_DATA),
                                                                     esp32.hall_sensor(),
                                                                     "{:.1f}".format(
                                                                         ((float(esp32.raw_temperature()) - 32.0)
                                                                          * 5 / 9))))
        print("2 -------SENSORDATA--------- 2")
        if (temp_avg is not None) and (rh_avg is not None) and (press_avg is not None):
            print("   Temp: %sC, Rh: %s, Pressure: %s" % (temp_avg, rh_avg, press_avg))
        if co2s.co2_average is not None:
            print("   CO2 is %s" % co2s.co2_average)
        if aq.aqinndex is not None:
            print("   AQ Index: %s" % ("{:.1f}".format(aq.aqinndex)))
            print("   PM1:%s (%s) PM2.5:%s (%s)" % (pms.pms_dictionary['PM1_0'], pms.pms_dictionary['PM1_0_ATM'],
                                             pms.pms_dictionary['PM2_5'], pms.pms_dictionary['PM2_5_ATM']))
            print("   PM10: %s (ATM: %s)" % (pms.pms_dictionary['PM10_0'], pms.pms_dictionary['PM10_0_ATM']))
            print("   %s < 0.3 & %s <0.5 " % (pms.pms_dictionary['PCNT_0_3'], pms.pms_dictionary['PCNT_0_5']))
            print("   %s < 1.0 & %s < 2.5" % (pms.pms_dictionary['PCNT_1_0'], pms.pms_dictionary['PCNT_2_5']))
            print("   %s < 5.0 & %s < 10.0" % (pms.pms_dictionary['PCNT_5_0'], pms.pms_dictionary['PCNT_10_0']))
        print("3 ---------FAULTS------------- 3")
        if BME280_f:
            print("BME280 sensor faulty!")
        if MHZ19_f:
            print("MHZ19 sensor faulty!")
        if PMS7003_f:
            print("PMS7003 sensor faulty!")
        if scr_f:
            print("Screen faulty!")
        await asyncio.sleep(5)


# Slow down speed due to heat production, max 240000000, normal 160000000, min with Wi-Fi 80000000
# freq(240000000)
freq(80000000)


# Particle sensor
try:
    pms = PARTICLES.PSensorPMS7003(uart=P_SEN_UART, rxpin=P_SEN_RX, txpin=P_SEN_TX)
    aq = AirQuality(pms)
except OSError as e:
    log_errors("Error: %s - Particle sensor init error!" % e)
    print("Error: %s - Particle sensor init error!" % e)
    PMS7003_f = True

# CO2 sensor
try:
    co2s = CO2.MHZ19bCO2(uart=CO2_SEN_UART, rxpin=CO2_SEN_RX_PIN, txpin=CO2_SEN_TX_PIN)
except OSError as e:
    log_errors("Error: %s - MHZ19 sensor init error!" % e)
    print("Error: %s - MHZ19 sensor init error!" % e)
    MHZ19_f = True

# BME280 sensor
i2c = SoftI2C(scl=Pin(I2C_SCL_PIN), sda=Pin(I2C_SDA_PIN))
try:
    bmes = BmE.BME280(i2c=i2c)
except OSError as e:
    log_errors("Error: %s - BME sensor init error!" % e)
    print("Error: %s - BME sensor init error!" % e)
    BME280_f = True
gc.collect()
gc.threshold(gc.mem_free() // 4 + gc.mem_alloc())

#  If you use UART2, you have to delete co2 object and re-create it after power on boot!
if reset_cause() == 1:
    del co2s
    sleep(5)  # 2 is not enough!
    co2s = CO2.MHZ19bCO2(uart=CO2_SEN_UART, rxpin=CO2_SEN_RX_PIN, txpin=CO2_SEN_TX_PIN)
#  Touchscreen and display init
t_spi = SPI(TS_SPI)  # HSPI
t_spi.init(baudrate=1100000, sck=Pin(TS_SCLK_PIN), mosi=Pin(TS_MOSI_PIN), miso=Pin(TS_MISO_PIN))
d_spi = SPI(TFT_SPI)  # VSPI - baudrate 40 - 90 MHz appears to be working, screen update still slow
d_spi.init(baudrate=50000000, sck=Pin(TFT_CLK_PIN), mosi=Pin(TFT_MOSI_PIN), miso=Pin(TFT_MISO_PIN))
try:
    disp = TFTDisplay(t_spi, d_spi)
    disp.scr_actv_time = time()
except MemoryError:
    log_errors("Display init memory error!")
    sleep(10)
    reset()
except OSError as e:
    log_errors("Error: %s - Touchscreen or display init error!" % e)
    raise TypeError("Error: %s - Touchscreen or display init error!" % e)

# Network handshake
net = WIFINET.ConnectWiFi(S1, P1, S2, P2, NTPS, DHCPN, SWEBR, WBRPLPW)


async def details_screen_loop():
    disp.scr_actv_time = time()
    if not scr_f and not PMS7003_f:
        r, r_c = await particle_screen()
        disp.d_scr_active = True
        try:
            await show_screen(r, r_c)
        except TypeError:
            pass
        await asyncio.sleep(S_UPDE_IVAL)
    if not scr_f and not BME280_f:
        r, r_c = await sensor_monitor()
        try:
            await show_screen(r, r_c)
        except TypeError:
            pass
        await asyncio.sleep(S_UPDE_IVAL)
    if not scr_f:
        r, r_c = await sys_monitor()
        try:
            await show_screen(r, r_c)
        except TypeError:
            pass
        await asyncio.sleep(S_UPDE_IVAL)
    if not scr_f:
        r, r_c = await net_monitor()
        try:
            await show_screen(r, r_c)
        except TypeError:
            pass
        await asyncio.sleep(S_UPDE_IVAL)
    disp.d_scr_active = False
    disp.t_tched = False


async def rot_scr():
    disp.scr_actv_time = time()
    disp.d_scr_active = True
    r, r_c = await particle_screen()
    if r is not None:
        try:
            await show_screen(r, r_c)
        except TypeError:
            pass
    await asyncio.sleep(S_UPDE_IVAL)
    r, r_c = await sensor_monitor()
    if r is not None:
        try:
            await show_screen(r, r_c)
        except TypeError:
            pass
    await asyncio.sleep(S_UPDE_IVAL)
    r, r_c = await sys_monitor()
    if r is not None:
        try:
            await show_screen(r, r_c)
        except TypeError:
            pass
    await asyncio.sleep(S_UPDE_IVAL)
    r, r_c = await net_monitor()
    if r is not None:
        try:
            await show_screen(r, r_c)
        except TypeError:
            pass
    await asyncio.sleep(S_UPDE_IVAL)
    disp.d_scr_active = False
    disp.t_tched = False


async def update_screen_loop():
    while True:
        if disp.t_tched is True:
            disp.backlight_on()
            if disp.d_scr_active is False:
                try:
                    await rot_scr()
                except TypeError:
                    await error_bckg()
                    disp.d.draw_text(disp.indent_p, 25 + disp.r_h * 2, "Please, wait!", disp.a_font, disp.cols["white"],
                                     disp.cols[disp.col_bckg])
                    disp.d.draw_text(disp.indent_p, 25 + disp.r_h * 3, "Sensors not ready!",
                                     disp.a_font, disp.cols["white"], disp.cols[disp.col_bckg])
                    disp.d.draw_text(disp.indent_p, 25 + disp.r_h * 4, "Thank you!", disp.a_font, disp.cols["white"],
                                     disp.cols[disp.col_bckg])
                    pass
            elif (disp.d_scr_active is True) and ((time() - disp.scr_actv_time) > disp.scr_tout):
                # Timeout
                disp.d_scr_active = False
                disp.t_tched = False
        else:
            if time() - disp.scr_actv_time <= BLIGHT_TOUT:
                disp.backlight_on()
            else:
                disp.backlight_off()
            r, r_c = await upd_welcome()
            await show_screen(r, r_c)


async def wait_timer():
    n = 0
    while (disp.t_tched is False) and (n <= disp.scr_upd_ival * 1000):
        await asyncio.sleep_ms(1)
        n += 1


async def show_screen(rows, row_colours):
    r1 = "AQ v1.0"
    r1_c = 'red'
    r2 = "1"
    r2_c = 'white'
    r3 = "2"
    r3_c = 'red'
    r4 = "3"
    r4_c = 'red'
    r5 = "4"
    r5_c = 'red'
    r6 = "5"
    r6_c = 'red'
    r7 = "6"
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
        if (co2s.co2_average > CO2_THOLD) or (co2s.co2_value > CO2_THOLD):
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
    if temp_avg is None:
        r4 = "Waiting values..."
        r4_c = 'yellow'
    else:
        r4 = "Lampo: %s (DP: %sC)" % (temp_avg, "{:.1f}".format(bmes.dew_point))
        if temp_avg > TEMP_THOLD:
            r4_c = 'red'
        else:
            r4_c = 'blue'
    if rh_avg is None:
        r5 = "Waiting values..."
        r5_c = 'yellow'
    else:
        r5 = "Kosteus: %s (%sM)" % (rh_avg, "{:.1f}".format(bmes.altitude))
        if rh_avg > RH_THOLD:
            r5_c = 'red'
        else:
            r5_c = 'blue'
    if press_avg is None:
        r6 = "Waiting values..."
        r6_c = 'yellow'
    else:
        r6 = "Paine: %s ATM" % press_avg
        if press_avg > PRESS_THOLD:
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
    if not BME280_f and not PMS7003_f and not MHZ19_f:
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
    row2 = "Free"
    row2_colour = 'blue'
    row3 = "Mem free: %s" % gc.mem_free()
    row3_colour = 'blue'
    row4 = "Mem allocated: %s" % gc.mem_alloc()
    row4_colour = 'blue'
    row5 = "Flash size: %s " % esp.flash_size()
    row5_colour = 'blue'
    row6 = "MCU Temp: %sC" % ("{:.1f}".format(((float(esp32.raw_temperature()) - 32.0) * 5 / 9)))
    row6_colour = 'blue'
    row7 = "Hall sensor %s" % esp32.hall_sensor()
    row7_colour = 'blue'
    rows = row1, row2, row3, row4, row5, row6, row7
    row_colours = row1_colour, row2_colour, row3_colour, row4_colour, row5_colour, row6_colour, row7_colour
    return rows, row_colours


async def net_monitor():
    if SNET == 1:
        row1 = "5. Network monitor"
        row1_colour = 'black'
        row2 = "AF: %s" % network.WLAN(network.AP_IF)
        row2_colour = 'blue'
        row3 = "Free"
        row3_colour = 'blue'
        row4 = "Free"
        row4_colour = 'blue'
        row5 = "Free"
        row5_colour = 'blue'
        row6 = "None:"
        row6_colour = 'blue'
        if b_upt is not 0:
            row7 = "Broker up %s" % b_upt[:-8]
        else:
            row7 = "Broker not connected"
        row7_colour = 'blue'
        rows = row1, row2, row3, row4, row5, row6, row7
        row_colours = row1_colour, row2_colour, row3_colour, row4_colour, row5_colour, row6_colour, row7_colour
        return rows, row_colours
    else:
        return None


def mqtt_publish():
    global last_update
    client = MQTTClient(CLID, MQSRV, MQP, MQUSR, MQPW,0,False)
    try:
        client.connect()
        if not PMS7003_f and (pms.pms_dictionary is not None) and ((time() - pms.startup_time) > pms.read_interval):
            client.publish(T_PM1_0, str(pms.pms_dictionary['PM1_0']), retain=0, qos=0)
            client.publish(T_PM1_0_ATM, str(pms.pms_dictionary['PM1_0_ATM']), retain=0, qos=0)
            client.publish(T_PM2_5, str(pms.pms_dictionary['PM2_5']), retain=0, qos=0)
            client.publish(T_PM2_5_ATM, str(pms.pms_dictionary['PM2_5_ATM']), retain=0, qos=0)
            client.publish(T_PM10_0, str(pms.pms_dictionary['PM10_0']), retain=0, qos=0)
            client.publish(T_PM10_0_ATM, str(pms.pms_dictionary['PM10_0_ATM']), retain=0, qos=0)
            client.publish(T_PCNT_0_3, str(pms.pms_dictionary['PCNT_0_3']), retain=0, qos=0)
            client.publish(T_PCNT_0_5, str(pms.pms_dictionary['PCNT_0_5']), retain=0, qos=0)
            client.publish(T_PCNT_1_0, str(pms.pms_dictionary['PCNT_1_0']), retain=0, qos=0)
            client.publish(T_PCNT_2_5, str(pms.pms_dictionary['PCNT_2_5']), retain=0, qos=0)
            client.publish(T_PCNT_5_0, str(pms.pms_dictionary['PCNT_5_0']), retain=0, qos=0)
            client.publish(T_PCNT_10_0, str(pms.pms_dictionary['PCNT_10_0']), retain=0, qos=0)
        if aq.aqinndex is not None:
            client.publish(T_AIRQ, str(aq.aqinndex), retain=0, qos=0)
        if not BME280_f:
            if temp_avg is not None:
                client.publish(T_TEMP, str(temp_avg), retain=0, qos=0)
            if bmes.values[2][:-1] is not None:
                client.publish(T_RH, str(rh_avg), retain=0, qos=0)
            if bmes.values[1][:-3] is not None:
                client.publish(T_PRESS, str(press_avg), retain=0, qos=0)
        if not MHZ19_f and (co2s.co2_average is not None):
            client.publish(T_CO2, str(co2s.co2_average), retain=0, qos=0)
        last_update = time()
        gc.collect()
        gc.threshold(gc.mem_free() // 4 + gc.mem_alloc())
        return True
    except OSError as e:
        log_errors("MQTT error %s:" %e)
        return False


async def update_mqtt_loop():
    global last_update
    while True:
        if net.net_ok and ((time()-last_update) > MQIVAL):
            try:
                mqtt_publish()
            except OSError as e:
                if DEBUG == 1:
                    print("Update loop OSError %s" %e)
        await asyncio.sleep(1)

async def main():
    loop = asyncio.get_event_loop()
    loop.create_task(pms.read_async_loop())
    loop.create_task(co2s.read_co2_loop())
    loop.create_task(aq.upd_aq_loop())
    loop.create_task(upd_status_loop())
    if DEBUG == 1:
        loop.create_task(show_what_i_do())
    loop.create_task(update_screen_loop())
    if SNET == 1:
        loop.create_task(net.net_upd_loop())
    if SMQTT == 1 and SNET ==1:
       loop.create_task(update_mqtt_loop())
    loop.run_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except MemoryError:
        log_errors("Memory Error in main!")
        reset()
