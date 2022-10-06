"""
This script is used for temperature, moisture and pressure measurument.
2 I2C channels, pins defined in the runtimeconfig.json. Asynchoronous code.

First BME280 is set to Pin(22) = SCL and Pin(21) = SDA. SDO is OPEN (first I2C bus)
Second BME280 is set to Pin(32) = SCL and Pin(33) = SDA. SDO is OPEN or GND (second I2C bus)
Third BME280 is set to Pin(32) = SCL and Pin(33) = SDA. SDO is connected to +3.3V! (second I2C bus)
If you need to change pins, do that in the parameters.py

If sensor is not found during object initialization, it will be skipped. Program continues even without sensors!

Sensor objects:
- bmes = First BME280 which uses default address 0x76 in I2C bus 1 !! SDO open !!
- bmet = Second BME280 which uses default address 0x76 in I2C bus 2 !! SDO open !!
- bmeu = Third BME280 which uses address 0x77 in I2C bus 2. !! SDO is connected to VCC !!

If you like to add fourth sensor, add code as you want. As an example:
- Optional: Fourth BME280 is set to Pin(32) = SCL and Pin(33) = SDA. SDO is connected to +3.3V! (first I2C bus)
- Optional: bmev = Fourth BME280 which uses address 0x77 in I2C bus 2 !! SDO is connected to VCC !!

Each sensor has MQTT messages for temperature, moisture and pressure defined in runtimeconfig.json.
- Optional: you can add altitude and deviation point information from the sensor if you like.

MQTT messages could be sent to Influxdb and from influxdb to Grafana.

Version: 6.10.2022: Jari Hiltunen & Tarmo Hiltunen

Tested with 3 x BME280 + ESP32-D Wroom (4Mb) + micropython version 1.19.1
"""
from machine import SoftI2C, Pin, freq, reset
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
sensor1faulty = False
sensor2faulty = False
sensor3faulty = False

try:
    f = open('parameters.py', "r")
    #  2 x I2C channels and their pins
    from parameters import I2C1_SCL_PIN, I2C1_SDA_PIN, I2C2_SCL_PIN, I2C2_SDA_PIN
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
        TOPIC_TEMP_1 = data['TOPIC_TEMP_1']
        TOPIC_RH_1 = data['TOPIC_RH_1']
        TOPIC_PRESSURE_1 = data['TOPIC_PRESSURE_1']
        TEMP_THOLD_1 = data['TEMP_TRESHOLD_1']
        TEMP_CORRECTION_1 = data['TEMP_CORRECTION_1']
        RH_THOLD_1 = data['RH_TRESHOLD_1']
        RH_CORRECTION_1 = data['RH_CORRECTION_1']
        P_THOLD_1 = data['PRESSURE_TRESHOLD_1']
        PRESSURE_CORRECTION_1 = data['PRESSURE_CORRECTION_1']
        TOPIC_TEMP_2 = data['TOPIC_TEMP_2']
        TOPIC_RH_2 = data['TOPIC_RH_2']
        TOPIC_PRESSURE_2 = data['TOPIC_PRESSURE_2']
        TEMP_THOLD_2 = data['TEMP_TRESHOLD_2']
        TEMP_CORRECTION_2 = data['TEMP_CORRECTION_2']
        RH_THOLD_2 = data['RH_TRESHOLD_2']
        RH_CORRECTION_2 = data['RH_CORRECTION_2']
        P_THOLD_2 = data['PRESSURE_TRESHOLD_2']
        PRESSURE_CORRECTION_2 = data['PRESSURE_CORRECTION_2']
        TOPIC_TEMP_3 = data['TOPIC_TEMP_3']
        TOPIC_RH_3 = data['TOPIC_RH_3']
        TOPIC_PRESSURE_3 = data['TOPIC_PRESSURE_3']
        TEMP_THOLD_3 = data['TEMP_TRESHOLD_3']
        TEMP_CORRECTION_3 = data['TEMP_CORRECTION_3']
        RH_THOLD_3 = data['RH_TRESHOLD_3']
        RH_CORRECTION_3 = data['RH_CORRECTION_3']
        P_THOLD_3 = data['PRESSURE_TRESHOLD_3']
        PRESSURE_CORRECTION_3 = data['PRESSURE_CORRECTION_3']

except OSError:
    print("Runtime parameters missing. Can not continue!")
    sleep(30)
    raise


def resolve_date():
    (year, month, mdate, hour, minute, second, wday, yday) = localtime()
    #  Finnish
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

# BME280 sensors I2C busses
i2c1 = SoftI2C(scl=Pin(I2C1_SCL_PIN), sda=Pin(I2C1_SDA_PIN))
i2c2 = SoftI2C(scl=Pin(I2C2_SCL_PIN), sda=Pin(I2C2_SDA_PIN))

try:
    bmes = BmE.BME280(i2c=i2c1)
except OSError as e:
    print("Error: %s - Sensor 1 (bmes) not connected!" % e)
    sensor1faulty = True
try:
    bmet = BmE.BME280(i2c=i2c2)  # Channel 2 0x76 address
except OSError as e:
    print("Error: %s - Sensor 2 (bmet) not connected!" % e)
    sensor2faulty = True
try:
    bmeu = BmE.BME280(i2c=i2c2, address=0x77)  # Channel 2 0x77 address (SDO set to 3.3V)
except OSError as e:
    print("Error: %s - Sensor 3 (bmeu) not connected!" % e)
    sensor3faulty = True


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
        if DEBUG_SCREEN_ACTIVE == 1:
            MQTTClient.DEBUG = True
        else:
            MQTTClient.DEBUG = False
        client = MQTTClient(config)
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
        await asyncio.sleep(5)
        if DEBUG_SCREEN_ACTIVE == 1:
            print('mqtt-publish', n)
        await client.publish('result', '{}'.format(n), qos=1)
        n += 1


async def mqtt_subscribe(client):
    # If "client" is missing, you get error from line 538 in MQTT_AS.py (1 given, expected 0)
    # This information is just to check if the broker is up, nothing else!!
    await client.subscribe('$SYS/broker/uptime', 1)


def update_mqtt_status(topic, msg, retained):
    global broker_uptime
    if DEBUG_SCREEN_ACTIVE == 1:
        print(resolve_date())
        print("MQTT receive topic: %s, message: %s, retained: %s" % (topic, msg, retained))
    if topic.decode('UTF-8') == '$SYS/broker/uptime':
        broker_uptime = msg.decode('UTF-8')

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
            if not sensor1faulty:
                if bmes.values[0][:-1] is not None:
                    await client.publish(TOPIC_TEMP_1, bmes.values[0][:-1], retain=0, qos=0)
                if bmes.values[2][:-1] is not None:
                    await client.publish(TOPIC_RH_1, bmes.values[2][:-1], retain=0, qos=0)
                if bmes.values[1][:-3] is not None:
                    await client.publish(TOPIC_PRESSURE_1, bmes.values[1][:-3], retain=0, qos=0)
            if not sensor2faulty:
                # I2C channel 2 sensor which SDO is open or set to GND
                if bmet.values[0][:-1] is not None:
                    await client.publish(TOPIC_TEMP_2, bmet.values[0][:-1], retain=0, qos=0)
                if bmet.values[2][:-1] is not None:
                    await client.publish(TOPIC_RH_2, bmet.values[2][:-1], retain=0, qos=0)
                if bmet.values[1][:-3] is not None:
                    await client.publish(TOPIC_PRESSURE_2, bmet.values[1][:-3], retain=0, qos=0)
            if not sensor3faulty:
                # I2C channel 2 sensor which SDO is open or set to VCC (3.3 or 5V depending sensor type)
                if bmeu.values[0][:-1] is not None:
                    await client.publish(TOPIC_TEMP_3, bmeu.values[0][:-1], retain=0, qos=0)
                if bmeu.values[2][:-1] is not None:
                    await client.publish(TOPIC_RH_3, bmeu.values[2][:-1], retain=0, qos=0)
                if bmeu.values[1][:-3] is not None:
                    await client.publish(TOPIC_PRESSURE_3, bmeu.values[1][:-3], retain=0, qos=0)


async def show_what_i_do():
    # Output is REPL

    while True:
        print(resolve_date())
        if START_NETWORK == 1:
            print("WiFi Connected %s" % net.net_ok)
            print("WiFi failed connects %s" % net.con_att_fail)
        if START_MQTT == 1:
            print("MQTT Connected %s" % mqtt_up)
            # print("MQTT broker uptime %s" % broker_uptime)
        print("Memory free: %s" % gc.mem_free())
        print("Memory alloc: %s" % gc.mem_alloc())
        print("-------")
        if sensor1faulty:
            print("Sensor 1 faulty!")
        else:
            print("-------")
            print("Sensor I2C channel 1 0x76")
            print("Temp: %s" % bmes.values[0][:-1])
            print("Moisture: %s" % bmes.values[2][:-1])
            print("Pressure: %s" % bmes.values[1][:-3])
        if sensor2faulty:
            print("Sensor 2 faulty!")
        else:
            print("-------")
            print("Sensor I2C channel 2 0x76")
            print("Temp: %s" % bmet.values[0][:-1])
            print("Moisture: %s" % bmet.values[2][:-1])
            print("Pressure: %s" % bmet.values[1][:-3])
        if sensor3faulty:
            print("Sensor 3 faulty!")
        else:
            print("-------")
            print("Sensor I2C channel 2 0x77")
            print("Temp: %s" % bmeu.values[0][:-1])
            print("Moisture: %s" % bmeu.values[2][:-1])
            print("Pressure: %s" % bmeu.values[1][:-3])
            print("-------")
        await asyncio.sleep(5)


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
