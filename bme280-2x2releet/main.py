"""
This script is used for temperature, moisture and pressure measurument and
for 2 x 2 relay control. Asynchoronous code.

First version: 14.12.2021: Jari Hiltunen
"""
from machine import I2C, Pin, freq, reset
import uasyncio as asyncio
from utime import mktime, localtime, sleep
import gc
from MQTT_AS import MQTTClient, config
import WIFICONN_AS as WifiNet
import BME280_float as BmE
from json import load
gc.collect()

# Globals
mqtt_up = False
broker_uptime = 0

try:
    f = open('parameters.py', "r")
    from parameters import I2C_SCL_PIN, I2C_SDA_PIN, RELAY1_PIN1, RELAY1_PIN2, RELAY2_PIN1, RELAY2_PIN2
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
        DEBUG_SCREEN_ACTIVE = data['DEBUG_SCREEN_ACTIVE']
        TOPIC_TEMP = data['TOPIC_TEMP']
        TOPIC_RH = data['TOPIC_RH']
        TOPIC_PRESSURE = data['TOPIC_PRESSURE']
        TEMP_THOLD = data['TEMP_TRESHOLD']
        TEMP_CORRECTION = data['TEMP_CORRECTION']
        RH_THOLD = data['RH_TRESHOLD']
        RH_CORRECTION = data['RH_CORRECTION']
        P_THOLD = data['PRESSURE_TRESHOLD']
        PRESSURE_CORRECTION = data['PRESSURE_CORRECTION']
        TOPIC_RELAY1_1 = data['TOPIC_RELAY1_1']
        TOPIC_RELAY1_2 = data['TOPIC_RELAY1_2']
        TOPIC_RELAY2_1 = data['TOPIC_RELAY2_1']
        TOPIC_RELAY2_2 = data['TOPIC_RELAY2_2']

except OSError:
    print("Runtime parameters missing. Can not continue!")
    sleep(30)
    raise


def resolve_date():
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


# Kick in some speed, max 240000000, normal 160000000, min with WiFi 80000000
freq(240000000)

# Network handshake
net = WifiNet.ConnectWiFi(SSID1, PASSWORD1, SSID2, PASSWORD2, NTPSERVER, DHCP_NAME, START_WEBREPL, WEBREPL_PASSWORD)

# BME280 sensor
i2c = I2C(scl=Pin(I2C_SCL_PIN), sda=Pin(I2C_SDA_PIN))
bmes = BmE.BME280(i2c=i2c)

# Relay objects. NC (Normally Closed) when 0 = on
relay1_1 = Pin(RELAY1_PIN1, Pin.OUT)
relay1_2 = Pin(RELAY1_PIN2, Pin.OUT)
relay2_1 = Pin(RELAY2_PIN1, Pin.OUT)
relay2_2 = Pin(RELAY2_PIN2, Pin.OUT)


async def mqtt_up_loop():
    global mqtt_up
    global client

    while net.net_ok is False:
        await asyncio.sleep(5)

    if net.net_ok is True:
        config['subs_cb'] = update_mqtt_status
        config['connect_coro'] = mqtt_subscribe
        config['ssid'] = net.use_ssid
        config['wifi_pw'] = net.u_pwd
        MQTTClient.DEBUG = False
        client = MQTTClient(config)
        await client.connect()
        mqtt_up = True

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
    await client.subscribe(TOPIC_RELAY1_1, 1)
    await client.subscribe(TOPIC_RELAY1_2, 1)
    await client.subscribe(TOPIC_RELAY2_1, 1)
    await client.subscribe(TOPIC_RELAY2_2, 1)


def update_mqtt_status(topic, msg, retained):
    # Note! relay commands are not asynchronous!
    global broker_uptime
    if DEBUG_SCREEN_ACTIVE == 1:
        print(resolve_date())
        print("MQTT receive topic: %s, message: %s, retained: %s" % (topic, msg, retained))
    if topic.decode('UTF-8') == '$SYS/broker/uptime':
        broker_uptime = msg.decode('UTF-8')
    if topic.decode('UTF-8') == TOPIC_RELAY1_1 and msg == b'0':
        relay1_1.value(0)
    if topic.decode('UTF-8') == TOPIC_RELAY1_1 and msg == b'1':
        relay1_1.value(1)
    if topic.decode('UTF-8') == TOPIC_RELAY1_2 and msg == b'0':
        relay1_2.value(0)
    if topic.decode('UTF-8') == TOPIC_RELAY1_2 and msg == b'1':
        relay1_2.value(1)
    if topic.decode('UTF-8') == TOPIC_RELAY2_1 and msg == b'0':
        relay2_1.value(0)
    if topic.decode('UTF-8') == TOPIC_RELAY2_1 and msg == b'1':
        relay2_1.value(1)
    if topic.decode('UTF-8') == TOPIC_RELAY2_2 and msg == b'0':
        relay2_2.value(0)
    if topic.decode('UTF-8') == TOPIC_RELAY2_2 and msg == b'1':
        relay2_2.value(1)

    """ Subscribe mqtt topics for correction multipliers and such. As an example, if
        temperature measurement is linearly wrong +0,8C, send substraction via mqtt-topic. If measurement is 
        not linearly wrong, pass range + correction to the topics.
        Example:
        if topic == '/device_id/temp/correction/':
            correction = float(msg)
            return correction """


async def mqtt_publish_loop():

    while True:
        if mqtt_up is False:
            await asyncio.sleep(10)
        else:
            await asyncio.sleep(MQTT_INTERVAL)  # Seconds
            if bmes.values[0][:-1] is not None:
                await client.publish(TOPIC_TEMP, bmes.values[0][:-1], retain=0, qos=0)
            if bmes.values[2][:-1] is not None:
                await client.publish(TOPIC_RH, bmes.values[2][:-1], retain=0, qos=0)
            if bmes.values[1][:-3] is not None:
                await client.publish(TOPIC_PRESSURE, bmes.values[1][:-3], retain=0, qos=0)


async def show_what_i_do():
    # Output is REPL

    while True:
        print(resolve_date())
        if START_NETWORK == 1:
            print("WiFi Connected %s" % net.net_ok)
            print("WiFi failed connects %s" % net.con_att_fail)
        if START_MQTT == 1:
            print("MQTT Connected %s" % mqtt_up)
            print("MQTT broker uptime %s" % broker_uptime)
        print("Memory free: %s" % gc.mem_free())
        print("Memory alloc: %s" % gc.mem_alloc())
        print("Temp: %s" % bmes.values[0][:-1])
        print("Moisture: %s" % bmes.values[2][:-1])
        print("Pressure: %s" % bmes.values[1][:-3])
        print("-------")
        await asyncio.sleep(5)


# For MQTT_AS
config['server'] = MQTT_SERVER
config['user'] = MQTT_USER
config['password'] = MQTT_PASSWORD
config['port'] = MQTT_PORT
config['client_id'] = CLIENT_ID
config['ssl'] = True
client = MQTTClient(config)


async def main():
    loop = asyncio.get_event_loop()
    if START_NETWORK == 1:
        loop.create_task(net.net_upd_loop())
    if DEBUG_SCREEN_ACTIVE == 1:
        loop.create_task(show_what_i_do())
    if START_MQTT == 1:
        loop.create_task(mqtt_up_loop())
        loop.create_task(mqtt_publish_loop())
    loop.run_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except MemoryError:
        reset()
