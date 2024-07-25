"""
This script is used for I2C connected OLED display, BME680 temperature/rh/pressure/voc sensor
MH-Z19B CO2 NDIR-sensor, PMS9103M particle sensor.

Values could be transferred by MQTT to the MQTT broker and from the broker to the Influxdb etc.

I2C for the OLED and BME680 are connected to SDA = Pin21 and SCL (SCK) = Pin22.
Use command i2c.scan() to check which devices respond from the I2C channel.

MH-Z19B and PMS9103M are connected to UART1 and UART2.

PMS9103M (9003M) datasheet https://evelta.com/content/datasheets/203-PMS9003M.pdf

Pinout (ledge upwards, PIN1 = right):
PIN1 = VCC = 5V
PIN2 = GND
PIN3 = SET (TTL 3.3V = normal working, GND = sleeping) = 4 *
PIN4 = RXD (3.3V) = 17
PIN5 = TXD (3.3V) = 16
PIN6 = RESET = 2 *
7,8 N/C.

MH-Z19B databseet: https://www.winsen-sensor.com/d/files/infrared-gas-sensor/mh-z19b-co2-ver1_0.pdf

Pinout (do not use 2,3 tx/rx otherwise pytool fails):
Vin = 5V
GND = GND
RX = 32
TX = 33

Program read sensor values once per second, rounds them to 1 decimal with correction values, then calculates averages.
Averages are sent to the MQTT broker.

For webrepl, remember to execute import webrepl_setup one time.

Asyncronous code.


Version 0.1 Jari Hiltunen -  xxxxxx
"""


from machine import SoftI2C, UART, Pin, freq, reset, ADC, TouchPad
import uasyncio as asyncio
from utime import time, mktime, localtime, sleep
import gc
import network
import drivers.WIFICONN_AS as WIFINET
import drivers.BME680 as BMES
import drivers.SH1106 as DP
import drivers.PMS9103M_AS as PARTS
import drivers.MHZ19B_AS as CO2
from drivers.AQI import AQI
gc.collect()
from json import load
import esp32
from drivers.MQTT_AS import MQTTClient, config
gc.collect()
# Globals
mqtt_up = False
broker_uptime = 0
co2_average = None
temp_average = None
rh_average = None
pressure_average = None
gas_average = None
BME_s_f = False
MHZ19_f = False
PMS_f = False
scr_f = False
last_update = time()


try:
    f = open('parameters.py', "r")
    from parameters import I2C_SCL_PIN, I2C_SDA_PIN, MH_UART, MH_RX, MH_TX, PMS_UART, PMS_RX, PMS_TX, PMS_RESET, PMS_SET
    f.close()
except OSError:  # open failed
    print("parameter.py-file missing! Can not continue!")
    raise

try:
    f = open('runtimeconfig.json', 'r')
    with open('runtimeconfig.json') as config_file:
        data = load(config_file)
        f.close()
        SID1 = data['SSID1']
        SID2 = data['SSID2']
        PW1 = data['PASSWORD1']
        PW2 = data['PASSWORD2']
        MQTT_S = data['MQTT_SERVER']
        MQTT_PWD = data['MQTT_PASSWORD']
        MQTT_U = data['MQTT_USER']
        MQTT_P = data['MQTT_PORT']
        MQTT_SSL = data['MQTT_SSL']
        MQTT_IVAL = data['MQTT_INTERVAL']
        CLIENT_ID = data['CLIENT_ID']
        T_ERR = data['TOPIC_ERRORS']
        WEBREPL_PWD = data['WEBREPL_PASSWORD']
        NTP_S = data['NTPSERVER']
        DHCP_N = data['DHCP_NAME']
        START_WBL = data['START_WEBREPL']
        START_NET = data['START_NETWORK']
        START_MQTT = data['START_MQTT']
        S_UPD_IVAL = data['SCREEN_UPDATE_INTERVAL']
        DEB_SCR_A = data['DEBUG_SCREEN_ACTIVE']
        SCR_TOUT = data['SCREEN_TIMEOUT']
        T_TEMP = data['TOPIC_TEMP']
        TEMP_THOLD = data['TEMP_TRESHOLD']
        TEMP_CORR = data['TEMP_CORRECTION']
        T_RH = data['TOPIC_RH']
        RH_THOLD = data['RH_TRESHOLD']
        RH_CORR = data['RH_CORRECTION']
        T_PRESS = data['TOPIC_PRESSURE']
        PRESS_CORR = data['PRESSURE_CORRECTION']
        PRESS_THOLD = data['PRESSURE_TRESHOLD']
        T_GASR = data['TOPIC_RGAS']
        GASR_CORR = data['RGAS_CORRECTION']
        GASR_THOLD = data['RGAS_TRESHOLD']
        T_CO2 = data['TOPIC_CO2']
        CO2_CORR = data['CO2_CORRECTION']
        CO2_THOLD = data['CO2_TRESHOLD']
        T_AIRQ = data['T_AIRQ']
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
        AQ_THOLD = data['AQ_THOLD']


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
                if DEB_SCR_A == 1:
                    print("MQTT error: %s" % e)
                    print("Config: %s" % config)
    n = 0
    while True:
        # await self.mqtt_subscribe()
        await asyncio.sleep(5)
        if DEB_SCR_A == 1:
            print('mqtt-publish', n)
        await client.publish('result', '{}'.format(n), qos=1)
        n += 1

async def mqtt_subscribe(client):
    # If "client" is missing, you get error from line 538 in MQTT_AS.py (1 given, expected 0)
    await client.subscribe('$SYS/broker/uptime', 1)

def update_mqtt_status(topic, msg, retained):
    global broker_uptime
    if DEB_SCR_A == 1:
        print((topic, msg, retained))
    broker_uptime = msg


async def show_what_i_do():
    # Output is REPL

    while True:
        print("\n1 ---------WIFI------------- 1")
        if START_NET == 1: #net.use_ssid,
            print("   WiFi Connected %s, hotspot: hidden, signal strength: %s" % (net.net_ok,  net.strength))
            # print("   IP-address: %s, connection attempts failed %s" % (net.ip_a, net.con_att_fail))
        if START_MQTT == 1:
            print("   MQTT Connected: %s, broker uptime: %s" % (mqtt_up, broker_uptime))
        print("   Memory free: %s, allocated: %s" % (gc.mem_free(), gc.mem_alloc()))
        print("2 -------SENSORDATA--------- 2")
        if (temp_average is not None) and (rh_average is not None) and (gas_average is not None):
            print("   Temp: %sC, Rh: %s, GasR: %s" % (temp_average, rh_average, gas_average))
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
        if BME_s_f:
            print("BME680 sensor faulty!")
        if MHZ19_f:
            print("MHZ19 sensor faulty!")
        if PMS_f:
            print("PMS9103M sensor faulty!")
        if scr_f:
            print("Screen faulty!")

        print("\n")
        await asyncio.sleep(5)


# Adjust speed to low heat production, max 240000000, normal 160000000, min with Wi-Fi 80000000
#  freq(240000000)
freq(80000000)

# Network handshake
net = WIFINET.ConnectWiFi(SID1, PW1, SID2, PW2, NTP_S, DHCP_N, START_WBL, WEBREPL_PWD)

i2c = SoftI2C(scl=Pin(I2C_SCL_PIN), sda=Pin(I2C_SDA_PIN))

try:
    bmes = BMES.BME680_I2C(i2c=i2c)
except OSError as e:
    raise Exception("Error: %s - BME sensor init error!" % e)

# Particle sensor
try:
    # Set SET to up (turn fan on)
    p_set = Pin(PMS_SET, Pin.OUT)
    p_set.value(1)
    pms = PARTS.PSensorPMS9103M(uart=PMS_UART, rxpin=PMS_RX, txpin=PMS_TX)
    aq = AirQuality(pms)
except OSError as e:
    # log_errors("Error: %s - Particle sensor init error!" % e)
    print("Error: %s - Particle sensor init error!" % e)
    PMS_f = True

# CO2 sensor
try:
    co2s = CO2.MHZ19bCO2(uart=MH_UART, rxpin=MH_RX, txpin=MH_TX)
except OSError as e:
    # log_errors("Error: %s - MHZ19 sensor init error!" % e)
    print("Error: %s - MHZ19 sensor init error!" % e)
    MHZ19_f = True

#  OLED display
try:
    display = Displayme()
except OSError as e:
    raise Exception("Error: %s - OLED Display init error!" % e)

# Touch thing
# touch = TouchPad(Pin(TOUCH_PIN))


async def upd_status_loop():
    # Other sensor loops are in their drivers
    global temp_average
    global rh_average
    global pressure_average
    global gas_average
    temp_list = []
    rh_list = []
    press_list = []
    gas_list = []

    while True:
        if not BME_s_f:
            try:
                temp_list.append(round(float(bmes.temperature)) + TEMP_CORR)
                rh_list.append(round(float(bmes.humidity)) + RH_CORR)
                press_list.append(round(float(bmes.pressure)) + PRESS_CORR)
                gas_list.append(round(float(bmes.gas)))
            except ValueError:
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


async def mqtt_publish_loop():
    #  Publish only valid average values.

    while True:
        if mqtt_up is False:
            await asyncio.sleep(10)
        else:
            await asyncio.sleep(MQTT_IVAL)
            if temp_average is not None:
                if -40 < temp_average < 100:
                    await client.publish(T_TEMP, str(temp_average), retain=0, qos=0)
                    # float to str conversion due to MQTT_AS.py len() issue
            if rh_average is not None:
                if 0 < rh_average < 100:
                    await client.publish(T_RH, str(rh_average), retain=0, qos=0)


# For MQTT_AS
config['server'] = MQTT_S
config['user'] = MQTT_U
config['password'] = MQTT_PWD
config['port'] = MQTT_P
config['client_id'] = CLIENT_ID
if MQTT_SSL == "True":
    config['ssl'] = True
else:
    config['ssl'] = False
client = MQTTClient(config)



async def disp_l():
    while True:
        await display.rot_180(True)
        await display.txt_2_r("  %s %s" % (resolve_date()[2], resolve_date()[0]), 0, 5)
        await display.txt_2_r("    %s" % resolve_date()[1], 1, 5)
        await display.txt_2_r("Temp:%s" % "{:.1f}".format(temp_average), 2, 5)
        await display.txt_2_r("Rh:%s" % "{:.1f}".format(rh_average), 3, 5)
        await display.txt_2_r("GasR: %s " "{:.1f}".format(gas_average), 4, 5)
        # row 5 await display.text_to_row("Alarms:%s " % alarms, 5, 5)
        await display.act_scr()
        await asyncio.sleep(1)

async def main():
    loop = asyncio.get_event_loop()
    if START_NET == 1:
        loop.create_task(net.net_upd_loop())
    if DEB_SCR_A == 1:
        loop.create_task(show_what_i_do())
    # if START_MQTT == 1:
       # loop.create_task(mqtt_up_loop())
       # loop.create_task(mqtt_publish_loop())
    loop.create_task(pms.read_async_loop())
    loop.create_task(co2s.read_co2_loop())
    loop.create_task(aq.upd_aq_loop())
    loop.create_task(upd_status_loop())
    loop.create_task(disp_l())
    loop.run_forever()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except MemoryError:
        reset()
