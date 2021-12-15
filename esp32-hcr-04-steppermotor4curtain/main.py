"""" This script controls inside curtain in the chicken house (or anything what 5V stepper motor can handle).

Operation basics: if outdoor is open (status updated via mqtt), measures distance from two HCSR-04 sensors and
if distance is > INSIDE_DISTANCE_CM or OUTSIDE_DISTANCE_CM, opens the curtain and keeps it up KEEP_CURTAIN_UP_DELAY
else closes the curtain. Limiter switch is for the upmost position detection.

Operation starts by rolling wire to the pulley from the lowest position. That value can be used for up - down steps
counter, but this version winds always up to the limiter switch.

Installation with ESP32 Dev Board: connect pins as in the parameters.py and for the echo-pin use either
  voltage splitter or level converter from 5V to 3.3V.

Stepper motor: 28BYJ-48, control board ULN2003. Lifts about 1 kg with 12V/1A PSU converted with LM2894 to 5V.

Sensors: HCSR-04 datasheet: https://datasheetspdf.com/pdf/1380136/ETC/HC-SR04/1
 Power Supply: +5V DC, Quiescent Current: <2mA, Working current: 15mA, Effectual Angle: <15º,
 Ranging Distance: 2-400 cm, Resolution: 0.3 cm, Measuring Angle: 30º, Trigger Input Pulse width: 10uS

Libraries:
 HCSR-04: https://github.com/rsc1975/micropython-hcsr04/blob/master/hcsr04.py
 MQTT_AS (not yet defined) https://github.com/peterhinch/micropython-mqtt/blob/master/mqtt_as/mqtt_as.py
 Stepper.py https://github.com/IDWizard/uln2003/blob/master/uln2003.py

3D cases for 28BYJ-48 and HSCSR-04 at https://www.thingiverse.com/thing:4714795 and
https://www.thingiverse.com/thing:4694604 and Fusion360 drawings for all of these at
https://gallery.autodesk.com/projects/esp32-related-stuff

14.12.2020 Jari Hiltunen
8.1.2021 Added limiter switch and fixed distance measuring so that WebREPL works
9.1.2021 Added mqtt connection which updates outdoor latch status and sends error reports
         Added parameters.py mqtt topic for outdoor latch, distances for inner and outer sensors
         Added to Steppermotor class status info is curtain motor stopped (0), opening (1) or closing (2)
25.02.2021 Changed to 12V stepper, now very strong but slow. Removed unncessary delay, stepper works now smooth.
"""


import Steppermotor
from machine import Pin, ADC, reset
import uasyncio as asyncio
import utime
import gc
from MQTT_AS import MQTTClient, config
import network
from hcsr04 import HCSR04


try:
    f = open('parameters.py', "r")
    from parameters import SSID1, SSID2, PASSWORD1, PASSWORD2, MQTT_SERVER, MQTT_PASSWORD, MQTT_USER, MQTT_PORT, \
        CLIENT_ID, BATTERY_ADC_PIN, TOPIC_ERRORS, STEPPER1_PIN1, STEPPER1_PIN2, STEPPER1_PIN3, STEPPER1_PIN4, \
        STEPPER1_DELAY, HCSR04_1_ECHO_PIN, HCSR04_1_TRIGGER_PIN, HCSR04_2_TRIGGER_PIN, HCSR04_2_ECHO_PIN, \
        LIMITER_SWITCH_PIN, TOPIC_OUTDOOR, INSIDE_DISTANCE_CM, OUTSIDE_DISTANCE_CM, KEEP_CURTAIN_UP_DELAY
except OSError:  # open failed
    print("parameter.py-file missing! Can not continue!")
    raise

#  Globals
previous_mqtt = utime.time()
outdoor_open = False
use_wifi_password = None


""" Network setup"""
if network.WLAN(network.STA_IF).config('essid') == SSID1:
    use_wifi_password = PASSWORD1
elif network.WLAN(network.STA_IF).config('essid') == SSID2:
    use_wifi_password = PASSWORD2


def restart_and_reconnect():
    #  Last resort
    print("About to reboot in 20s... ctrl + c to break")
    utime.sleep(20)
    reset()


class StepperMotor:
    """ ULN2003-based control, half_steps, asynchronous setup. """

    def __init__(self, in1, in2, in3, in4, indelay):
        self.motor = Steppermotor.create(Pin(in1, Pin.OUT), Pin(in2, Pin.OUT), Pin(in3, Pin.OUT),
                                         Pin(in4, Pin.OUT), delay=indelay)
        self.full_rotation = int(4075.7728395061727 / 8)  # http://www.jangeox.be/2013/10/stepper-motor-28byj-48_25.html
        self.uplimit = 0
        self.toplimit = 500
        self.curtain_steps = 0
        self.up_down_delay_ms = 500
        self.curtain_rolling = 0  # 0 = not rolling, 1 = rolling up, 2 = rolling down
        self.curtain_up = False
        self.curtain_up_time = None
        self.curtain_down_time = None

    async def step_up(self):
        if limiter_switch.value() == 0:
            try:
                self.motor.step(1, -1)
            except OSError as ex:
                print('ERROR stepping up:', ex)
                await error_reporting('ERROR stepping up: %s' % ex)

    async def step_down(self):
        try:
            self.motor.step(1)
        except OSError as ex:
            print('ERROR stepping down:', ex)
            await error_reporting('ERROR stepping down: %s' % ex)

    async def wind_to_toplimiter(self):
        print("Starting uprotation...")
        n = 0
        starttime = utime.ticks_ms()
        self.curtain_rolling = 1
        while (self.curtain_up is False) and ((utime.ticks_ms() - starttime) < 90000):
            if limiter_switch.value() == 0:
                await self.step_up()
                n += 1
            else:
                self.curtain_up = True
                self.curtain_up_time = utime.localtime()
                self.up_down_delay_ms = utime.ticks_ms() - starttime
                self.curtain_steps = n
                self.curtain_rolling = 0
                await self.zero_to_position()
                print("Found top, steps taken %s" % self.curtain_steps)

    async def roll_curtain_down(self):
        print("Starting downrotation ...")
        self.curtain_rolling = 2
        for x in range(self.curtain_steps):
            await self.step_down()
        self.curtain_up = False
        self.curtain_rolling = 0
        self.curtain_down_time = utime.localtime()

    async def wind_x_rotations(self, y):
        self.curtain_rolling = 1
        for x in range(y):
            await self.step_up()
        self.curtain_rolling = 0

    async def release_x_rotations(self, y):
        self.curtain_rolling = 2
        for x in range(y):
            await self.step_down()
        self.curtain_rolling = 0

    async def zero_to_position(self):
        self.motor.reset()


class DistanceSensor:

    def __init__(self, trigger, echo):
        self.sensor = HCSR04(trigger_pin=trigger, echo_pin=echo)
        self.distancecm = None
        self.distancemm = None

    async def measure_distance_cm(self):
        try:
            distance = self.sensor.distance_cm()
            if distance > 0:
                self.distancecm = distance
                await asyncio.sleep_ms(100)
            else:
                self.distancecm = None
        except OSError as ex:
            print('ERROR getting distance:', ex)
            await error_reporting(ex)

    async def measure_distance_cm_loop(self):
        while True:
            await self.measure_distance_cm()
            await asyncio.sleep_ms(100)

    async def measure_distance_mm(self):
        try:
            distance = self.sensor.distance_mm()
            if distance > 0:
                self.distancemm = distance
                await asyncio.sleep_ms(100)
            else:
                self.distancemm = None
        except OSError as ex:
            print('ERROR getting distance:', ex)
            await error_reporting(ex)

    async def measure_distance_mm_loop(self):
        while True:
            await self.measure_distance_mm()
            await asyncio.sleep_ms(100)


def resolve_date():
    (year, month, mdate, hour, minute, second, wday, yday) = utime.localtime()
    date = "%s.%s.%s time %s:%s:%s" % (mdate, month, year, "{:02d}".format(hour), "{:02d}".format(minute), "{:02d}".
                                       format(second))
    return date


async def error_reporting(error):
    # error message: date + time;uptime;devicename;ip;error;free mem
    errormessage = str(resolve_date()) + ";" + str(utime.ticks_ms()) + ";" \
        + str(CLIENT_ID) + ";" + str(network.WLAN(network.STA_IF).ifconfig()) + ";" + str(error) +\
        ";" + str(gc.mem_free())
    await client.publish(TOPIC_ERRORS, str(errormessage), retain=False)


async def mqtt_up_loop():
    #  This loop just keeps the mqtt connection up
    await mqtt_subscribe(client)
    n = 0
    while True:
        await asyncio.sleep(5)
        print('mqtt-publish', n)
        await client.publish('result', '{}'.format(n), qos=1)
        n += 1


async def mqtt_subscribe(client):
    await client.subscribe(TOPIC_OUTDOOR, 0)


def update_outdoor_status(topic, msg, retained):
    global outdoor_open
    # print("Topic: %s, message %s" % (topic, msg))
    status = int(msg)
    if status == 1:
        print("Outdoor status: opened")
        outdoor_open = True
    elif status == 0:
        print("Outdoor status: close")
        outdoor_open = False


pulley_motor = StepperMotor(STEPPER1_PIN1, STEPPER1_PIN2, STEPPER1_PIN3, STEPPER1_PIN4, STEPPER1_DELAY)
inside_distance = DistanceSensor(HCSR04_1_TRIGGER_PIN, HCSR04_1_ECHO_PIN)
outside_distance = DistanceSensor(HCSR04_2_TRIGGER_PIN, HCSR04_2_ECHO_PIN)
limiter_switch = Pin(LIMITER_SWITCH_PIN, Pin.IN, Pin.PULL_UP)


async def show_what_i_do():
    while True:
        print("Distances: inside: %s, outside: %s" % (inside_distance.distancecm, outside_distance.distancecm))
        print("Switch status: %s, pulley motor status: %s" % (limiter_switch.value(), pulley_motor.curtain_rolling))
        print("Outdoor open: %s, curtain steps: %s, curtain is up: %s " % (outdoor_open, pulley_motor.curtain_steps,
                                                                           pulley_motor.curtain_up))
        print("-------")
        await asyncio.sleep(1)

# Asynchronous mqtt for updating outdoor mqtt status and sending errors to database
config['server'] = MQTT_SERVER
config['ssid'] = network.WLAN(network.STA_IF).config('essid')
config['wifi_pw'] = use_wifi_password
config['user'] = MQTT_USER
config['password'] = MQTT_PASSWORD
config['port'] = MQTT_PORT
config['client_id'] = CLIENT_ID
config['subs_cb'] = update_outdoor_status
config['connect_coro'] = mqtt_subscribe
client = MQTTClient(config)


async def main():
    MQTTClient.DEBUG = False
    try:
        await client.connect()
    except OSError as ex:
        print("Error %s. Perhaps mqtt username or password is wrong or missing or broker down?" % ex)
        raise
    asyncio.create_task(mqtt_up_loop())
    asyncio.create_task(show_what_i_do())
    #  Initialize distance reading loops
    asyncio.create_task(inside_distance.measure_distance_cm_loop())
    asyncio.create_task(outside_distance.measure_distance_cm_loop())
    # Curtain shall be down when operation is started, but if limiter switch is 1, then we
    # have to first release some wire to lower the curtain.
    if limiter_switch.value() == 1:
        await pulley_motor.release_x_rotations(5833)   # about 35 cm with 1:4 gear ratio
    #  Rotate pulley until limiter switch is 1 - wait time max 60 seconds
    await pulley_motor.wind_to_toplimiter()
    # if pulley_motor.curtain_steps = 0, then operation failed to find top position
    if pulley_motor.curtain_steps == 0:
        print("Check limiter switch!")
        await error_reporting("Check limiter switch!")
        utime.sleep(30)
        raise
    # more wire
    # await pulley_motor.release_x_rotations(1000)
    # less wire
    # await pulley_motor.wind_x_rotations(1000)

    while True:
        if outdoor_open is True:
            if inside_distance.distancecm is not None:
                if (inside_distance.distancecm <= INSIDE_DISTANCE_CM) and (pulley_motor.curtain_up is False) and \
                        (pulley_motor.curtain_rolling == 0):
                    await pulley_motor.wind_to_toplimiter()
                elif (inside_distance.distancecm > INSIDE_DISTANCE_CM) and (pulley_motor.curtain_up is True) and \
                        (pulley_motor.curtain_rolling == 0) and \
                        ((utime.mktime(utime.localtime()) - utime.mktime(pulley_motor.curtain_up_time)) >
                         KEEP_CURTAIN_UP_DELAY):
                    await pulley_motor.roll_curtain_down()
            if outside_distance.distancecm is not None:
                if (outside_distance.distancecm <= OUTSIDE_DISTANCE_CM) and (pulley_motor.curtain_up is False) and \
                        (pulley_motor.curtain_rolling == 0):
                    await pulley_motor.wind_to_toplimiter()
                elif (outside_distance.distancecm > OUTSIDE_DISTANCE_CM) and (pulley_motor.curtain_up is True) and \
                     (pulley_motor.curtain_rolling == 0) and \
                        ((utime.mktime(utime.localtime()) - utime.mktime(pulley_motor.curtain_up_time)) >
                         KEEP_CURTAIN_UP_DELAY):
                    await pulley_motor.roll_curtain_down()
        elif (outdoor_open is False) and (pulley_motor.curtain_up is True):
            await pulley_motor.roll_curtain_down()
        await asyncio.sleep(1)

try:
    asyncio.run(main())
except:
    restart_and_reconnect()
