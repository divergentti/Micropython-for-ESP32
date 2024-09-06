"""
MicroPython v1.22.1 on 2024-01-05; Generic ESP32 module with ESP32

This script is used for temperature, moisture and pressure measurement and
for 2 x 2 relay control. Asynchronous code.

First version: 14.12.2021: Jari Hiltunen
Updated 2.2.2024: added average calculation, updated MQTT loop, shortened variable names, removed date_time,
    added MQTT_SSL to runtimeconfig.json
"""
from machine import I2C, Pin, freq, reset
import uasyncio as asyncio
import gc
from MQTT_AS import MQTTClient, config
import WIFICONN_AS as WNET
import BME280_float as BMES
from json import load
gc.collect()

# Globals
mqtt_up = False
broker_uptime = 0
s_1_temp_ave = -200
s_1_rh_ave = -200
s_1_pres_ave = -200

try:
    f = open('parameters.py', "r")
    from parameters import I2C_SCL_PIN, I2C_SDA_PIN, RELAY1_PIN1, RELAY1_PIN2, RELAY2_PIN1, RELAY2_PIN2
    f.close()
except OSError as e:  # open failed
    raise ("Error: ", e, "parameter.py-file missing! Can not continue!")


try:
    f = open('runtimeconfig.json', 'r')
    with open('runtimeconfig.json') as con_file:
        data = load(con_file)
        f.close()
        SID1 = data['SSID1']
        SID2 = data['SSID2']
        PWD1 = data['PASSWORD1']
        PWD2 = data['PASSWORD2']
        MQTT_SSL = data['MQTT_SSL']
        MQTT_SRV = data['MQTT_SERVER']
        MQTT_PWD = data['MQTT_PASSWORD']
        MQTT_U = data['MQTT_USER']
        MQTT_P = data['MQTT_PORT']
        MQTT_IVAL = data['MQTT_INTERVAL']
        CLIENT_ID = data['CLIENT_ID']
        T_ERR = data['TOPIC_ERRORS']
        WEBREPL_PWD = data['WEBREPL_PASSWORD']
        NTPSERV = data['NTPSERVER']
        DHCP_NAME = data['DHCP_NAME']
        S_WEBRBL = data['START_WEBREPL']
        S_NET = data['START_NETWORK']
        S_MQTT = data['START_MQTT']
        D_SCR_ACT = data['DEBUG_SCREEN_ACTIVE']
        T_TEMP = data['TOPIC_TEMP']
        T_RH = data['TOPIC_RH']
        T_PRES = data['TOPIC_PRESSURE']
        TEMP_THOLD = data['TEMP_TRESHOLD']
        TEMP_CORR = data['TEMP_CORRECTION']
        RH_THOLD = data['RH_TRESHOLD']
        RH_CORR = data['RH_CORRECTION']
        P_THOLD = data['PRESSURE_TRESHOLD']
        PRESS_CORR = data['PRESSURE_CORRECTION']
        T_R_1_1 = data['TOPIC_RELAY1_1']
        T_R_1_2 = data['TOPIC_RELAY1_2']
        T_R_2_1 = data['TOPIC_RELAY2_1']
        T_R_2_2 = data['TOPIC_RELAY2_2']

except OSError as e:
    raise ("Error: ", e, " in runtimeconfig.json load!")

# Kick in some speed, max 240000000, normal 160000000, min with Wi-Fi 80000000
freq(160000000)

# Network handshake
net = WNET.ConnectWiFi(SID1, PWD1, SID2, PWD2, NTPSERV, DHCP_NAME, S_WEBRBL, WEBREPL_PWD)

# BME280 sensor
i2c = I2C(scl=Pin(I2C_SCL_PIN), sda=Pin(I2C_SDA_PIN))
s1 = BMES.BME280(i2c=i2c)

# Relay objects. NC (Normally Closed) when 0 = on
relay1_1 = Pin(RELAY1_PIN1, Pin.OUT)
relay1_2 = Pin(RELAY1_PIN2, Pin.OUT)
relay2_1 = Pin(RELAY2_PIN1, Pin.OUT)
relay2_2 = Pin(RELAY2_PIN2, Pin.OUT)


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
            if D_SCR_ACT == 1:
                MQTTClient.DEBUG = True
            else:
                MQTTClient.DEBUG = False

            client = MQTTClient(config)

            try:
                await client.connect()
            except OSError as e:
                if D_SCR_ACT == 1:
                    mqtt_up = False
                    print("Error", e, " MQTT client connect failed")
            else:
                mqtt_up = True
        elif (net.net_ok is True) and (mqtt_up is True):
            await asyncio.sleep(5)
            if D_SCR_ACT == 1:
                print('mqtt-publish', n)
            await client.publish('result', '{}'.format(n), qos=1)
            n += 1


async def mqtt_subs(client):
    # If "client" is missing, you get error from line 538 in MQTT_AS.py (1 given, expected 0)
    await client.subscribe('$SYS/broker/uptime', 1)
    await client.subscribe(T_R_1_1, 1)
    await client.subscribe(T_R_1_2, 1)
    await client.subscribe(T_R_2_1, 1)
    await client.subscribe(T_R_2_2, 1)


def upd_mqtt_stat(topic, msg, retained):
    # Note! relay commands are not asynchronous!
    global broker_uptime
    if D_SCR_ACT == 1:
        print("MQTT receive topic: %s, message: %s, retained: %s" % (topic, msg, retained))
    if topic.decode('UTF-8') == '$SYS/broker/uptime':
        broker_uptime = msg.decode('UTF-8')
    if topic.decode('UTF-8') == T_R_1_1 and msg == b'0':
        relay1_1.value(0)
    if topic.decode('UTF-8') == T_R_1_1 and msg == b'1':
        relay1_1.value(1)
    if topic.decode('UTF-8') == T_R_1_2 and msg == b'0':
        relay1_2.value(0)
    if topic.decode('UTF-8') == T_R_1_2 and msg == b'1':
        relay1_2.value(1)
    if topic.decode('UTF-8') == T_R_2_1 and msg == b'0':
        relay2_1.value(0)
    if topic.decode('UTF-8') == T_R_2_1 and msg == b'1':
        relay2_1.value(1)
    if topic.decode('UTF-8') == T_R_2_2 and msg == b'0':
        relay2_2.value(0)
    if topic.decode('UTF-8') == T_R_2_2 and msg == b'1':
        relay2_2.value(1)

    """ Subscribe mqtt topics for correction multipliers and such. As an example, if
        temperature measurement is linearly wrong +0,8C, send substraction via mqtt-topic. If measurement is 
        not linearly wrong, pass range + correction to the topics.
        Example:
        if topic == '/device_id/temp/correction/':
            correction = float(msg)
            return correction """


async def r_sens_loop():
    global s_1_temp_ave, s_1_rh_ave, s_1_pres_ave
    s1_temp_list = []
    s1_rh_list = []
    s1_press_list = []

    #  Read values from sensor once per second, add them to the array, delete oldest when size 10
    while True:
        s1_temp_list.append(round(float(s1.values[0][:-1]), 1) + TEMP_CORR)
        s1_rh_list.append(round(float(s1.values[2][:-1]), 1) + RH_CORR)
        s1_press_list.append(round(float(s1.values[1][:-3]), 1) + PRESS_CORR)
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


async def mqtt_pub_loop():
    while True:
        if mqtt_up is False:
            gc.collect()
            gc.threshold(gc.mem_free() // 4 + gc.mem_alloc())
            await asyncio.sleep(10)
        elif mqtt_up is True:
            await asyncio.sleep(MQTT_IVAL)  # Seconds
            if -40 < s_1_temp_ave < 100:
                await client.publish(T_TEMP, str(s_1_temp_ave), retain=0, qos=0)
            if 0 < s_1_rh_ave < 100:
                await client.publish(T_RH, str(s_1_rh_ave), retain=0, qos=0)
            if 0 < s_1_pres_ave < 5000:
                await client.publish(T_PRES, str(s_1_pres_ave), retain=0, qos=0)


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
config['port'] = MQTT_P
config['client_id'] = CLIENT_ID
if MQTT_SSL == 1:
    config['ssl'] = True
else:
    config['ssl'] = False
client = MQTTClient(config)


async def main():
    loop = asyncio.get_event_loop()
    if S_NET == 1:
        loop.create_task(net.net_upd_loop())
    if D_SCR_ACT == 1:
        loop.create_task(show_what_i_do())
    if S_MQTT == 1:
        loop.create_task(mqtt_up_loop())
        loop.create_task(mqtt_pub_loop())
    loop.create_task(r_sens_loop())
    loop.run_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except MemoryError:
        reset()
