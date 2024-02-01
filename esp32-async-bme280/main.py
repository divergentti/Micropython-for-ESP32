"""

MicroPython v1.22.1 on 2024-01-05; Generic ESP32 module with ESP32

This script is used for temperature, moisture and pressure measurement.
I2C channel, pins defined in the runtimeconfig.json. Asynchronous code.

BME280 is set to Pin(22) = SCL and Pin(21) = SDA. SDO is OPEN (first I2C bus). Check parameters.py

MQTT messages could be sent to Influxdb and from influxdb to Grafana.

Version 0.1 - 01.02.2024 - Jari Hiltunen (Divergentti)

"""
from machine import SoftI2C, Pin, freq, reset
import uasyncio as asyncio
import gc
from MQTT_AS import MQTTClient, config
import WIFICONN_AS as WNET
import BME280_float as BME
from json import load
import esp32
gc.collect()
gc.threshold(gc.mem_free() // 4 + gc.mem_alloc())

# Globals
mqtt_up = False
broker_uptime = 0
# Int values which are out of scope
s_1_temp_ave = -200
s_1_rh_ave = -200
s_1_pres_ave = -200


try:
    f = open('parameters.py', "r")
    from parameters import I2C1_SCL_PIN, I2C1_SDA_PIN
    f.close()
except OSError as e:
    raise ValueError("Error: %s - parameter.py-file missing! Can not continue!" % e)


try:
    f = open('runtimeconfig.json', 'r')
    with open('runtimeconfig.json') as config_file:
        data = load(config_file)
        f.close()
        SID1 = data['SSID1']
        SID2 = data['SSID2']
        PWD1 = data['PASSWORD1']
        PWD2 = data['PASSWORD2']
        MQTT_SRV = data['MQTT_SERVER']
        MQTT_PWD = data['MQTT_PASSWORD']
        MQTT_U = data['MQTT_USER']
        MQTT_PRT = data['MQTT_PORT']
        MQTT_IVAL = data['MQTT_INTERVAL']
        CLIENT_ID = data['CLIENT_ID']
        T_ERR = data['TOPIC_ERRORS']
        WEBREPL_PWD = data['WEBREPL_PASSWORD']
        NTP_SRV = data['NTPSERVER']
        DHCP_NAME = data['DHCP_NAME']
        S_WEBREPL = data['START_WEBREPL']
        S_NET = data['START_NETWORK']
        S_MQTT = data['START_MQTT']
        DEB_SCR_ACT = data['DEBUG_SCREEN_ACTIVE']
        T_TEMP_1 = data['TOPIC_TEMP_1']
        T_RH_1 = data['TOPIC_RH_1']
        T_PRES_1 = data['TOPIC_PRESSURE_1']
        TEMP_THOLD_1 = data['TEMP_TRESHOLD_1']
        TEMP_CORR_1 = data['TEMP_CORRECTION_1']
        RH_THOLD_1 = data['RH_TRESHOLD_1']
        RH_CORR_1 = data['RH_CORRECTION_1']
        P_THOLD_1 = data['PRESSURE_TRESHOLD_1']
        PRESS_CORR_1 = data['PRESSURE_CORRECTION_1']

except OSError as e:
    raise ValueError("Error %s: Runtime parameters missing. Can not continue!" % e)


# Kick in some speed, max 240000000, normal 160000000, min with Wi-Fi 80000000
# freq(240000000)
freq(80000000)

# Network handshake
net = WNET.ConnectWiFi(SID1, PWD1, SID2, PWD2, NTP_SRV, DHCP_NAME, S_WEBREPL, WEBREPL_PWD)

# BME280 sensors I2C busses
i2c1 = SoftI2C(scl=Pin(I2C1_SCL_PIN), sda=Pin(I2C1_SDA_PIN))


try:
    bmes = BME.BME280(i2c=i2c1)
except OSError as e:
    raise "Error: %s - Sensor 1 (bmes) not connected!" % e


async def read_sensors_loop():
    global s_1_temp_ave, s_1_rh_ave, s_1_pres_ave
    s1_temp_list = []
    s1_rh_list = []
    s1_press_list = []

    #  Read values from sensor once per second, add them to the array, delete oldest when size 10
    while True:
        s1_temp_list.append(round(float(bmes.values[0][:-1]), 1) + TEMP_CORR_1)
        s1_rh_list.append(round(float(bmes.values[2][:-1]), 1) + RH_CORR_1)
        s1_press_list.append(round(float(bmes.values[1][:-3]), 1) + PRESS_CORR_1)
        gc.collect()
        gc.threshold(gc.mem_free() // 4 + gc.mem_alloc())
        if len(s1_temp_list) >= 10:
            s1_temp_list.pop(0)
        if len(s1_rh_list) >= 10:
            s1_rh_list.pop(0)
        if len(s1_press_list) >= 10:
            s1_press_list.pop(0)

        if len(s1_temp_list) > 1:
            s_1_temp_ave = round(sum(s1_temp_list) / len(s1_temp_list), 1)
        if len(s1_rh_list) > 1:
            s_1_rh_ave = round(sum(s1_rh_list) / len(s1_rh_list), 1)
        if len(s1_press_list) > 1:
            s_1_pres_ave = round(sum(s1_press_list) / len(s1_press_list), 1)
        gc.collect()
        gc.threshold(gc.mem_free() // 4 + gc.mem_alloc())
        await asyncio.sleep(1)


async def mqtt_up_loop():
    global mqtt_up
    global client
    n = 0

    while True:
        if net.net_ok is False:
            # Let network do handshake first
            await asyncio.sleep(5)
        elif (net.net_ok is True) and (mqtt_up is False):
            config['subs_cb'] = upd_mqtt_stat
            config['connect_coro'] = mqtt_subs
            config['ssid'] = net.use_ssid
            config['wifi_pw'] = net.u_pwd
            if DEB_SCR_ACT == 1:
                MQTTClient.DEBUG = True
            else:
                MQTTClient.DEBUG = False

            client = MQTTClient(config)

            try:
                await client.connect()
            except OSError as e:
                if DEB_SCR_ACT == 1:
                    mqtt_up = False
                    print("Error", e, " MQTT client connect failed")
            else:
                mqtt_up = True
        elif (net.net_ok is True) and (mqtt_up is True):
            await asyncio.sleep(5)
            if DEB_SCR_ACT == 1:
                print('mqtt-publish', n)
            await client.publish('result', '{}'.format(n), qos=1)
            n += 1


async def mqtt_subs(client):
    # If "client" is missing, you get error from line 538 in MQTT_AS.py (1 given, expected 0)
    # This is just to check if the broker is up, nothing else. You may skip this.
    await client.subscribe('$SYS/broker/uptime', 1)


def upd_mqtt_stat(topic, msg, retained):
    global broker_uptime
    if DEB_SCR_ACT == 1:
        print("MQTT receive topic: %s, message: %s, retained: %s" % (topic, msg, retained))
    if topic.decode('UTF-8') == '$SYS/broker/uptime':
        broker_uptime = msg.decode('UTF-8')


async def mqtt_publish_loop():

    while True:
        if mqtt_up is False:
            gc.collect()
            gc.threshold(gc.mem_free() // 4 + gc.mem_alloc())
            await asyncio.sleep(10)
        else:
            await asyncio.sleep(MQTT_IVAL)  # Seconds
            if -40 < s_1_temp_ave < 100 and s_1_temp_ave:
                await client.publish(T_TEMP_1, str(s_1_temp_ave), retain=0, qos=0)
            if 0 < s_1_rh_ave < 100:
                await client.publish(T_RH_1, str(s_1_rh_ave), retain=0, qos=0)
            if 0 < s_1_pres_ave < 5000:
                await client.publish(T_PRES_1, str(s_1_pres_ave), retain=0, qos=0)


async def show_what_i_do():
    # Output is REPL

    while True:
        print("\n1 ---------WIFI------------- 1")
        if S_NET == 1:
            print("   WiFi Connected %s, hotspot: %s, signal strength: %s" % (net.net_ok, net.use_ssid, net.strength))
            print("   IP-address: %s" % net.ip_a)
        if S_MQTT == 1:
            print("   MQTT Connected: %s, broker uptime: %s" % (mqtt_up, broker_uptime))
        print("   Memory free: %s, allocated: %s" % (gc.mem_free(), gc.mem_alloc()))
        print("2 -------SENSORDATA--------- 2")
        if (s_1_temp_ave is not None) and (s_1_rh_ave is not None) and (s_1_pres_ave is not None):
            print("   Sensor1: Temp: %sC, Rh: %s, Pressure: %s" % (s_1_temp_ave, s_1_rh_ave, s_1_pres_ave))

        await asyncio.sleep(5)


# For MQTT_AS
config['server'] = MQTT_SRV
config['user'] = MQTT_U
config['password'] = MQTT_PWD
config['port'] = MQTT_PRT
config['client_id'] = CLIENT_ID
config['ssl'] = False
client = MQTTClient(config)


async def main():
    loop = asyncio.get_event_loop()
    if S_NET == 1:
        loop.create_task(net.net_upd_loop())
    if DEB_SCR_ACT == 1:
        loop.create_task(show_what_i_do())
    if S_MQTT == 1:
        loop.create_task(mqtt_up_loop())
        loop.create_task(mqtt_publish_loop())
    loop.create_task(read_sensors_loop())
    loop.run_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except MemoryError:
        reset()
