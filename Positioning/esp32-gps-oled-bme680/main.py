"""
Version 0.2 Jari Hiltunen / Divergentti
Updated: 2.6.2023

Sample script to show how OLED, BME680 and Neo6M GPS-module may be used together.
Logs values into csv- formatted file every minute.
Filename = val-daynumber.csv, path /data
Check if file space is less than 20000 and starts rotation by deleting oldest file

ESP32 with esp32-ota-20230426-v1.20.0.bin micropython.

I2C for the OLED and BME680 are connected to SDA = Pin21 and SCL (SCK) = Pin22.
Use command i2c.scan() to check which devices respond from the I2C channel.

Mostly asyncronous code.
"""


from machine import SoftI2C, Pin, freq, reset, TouchPad, reset_cause
import uasyncio as asyncio
from utime import mktime, localtime, sleep
import os
import gc
import drivers.BME680 as BMESENSOR
import drivers.SH1106 as OLEDDISPLAY
import drivers.GPS_AS as GPS
gc.collect()
from json import load
import esp32

gc.collect()
# Globals
temp_average = None
rh_average = None
pressure_average = None
gas_average = None
BME680_sensor_faulty = False


try:
    f = open('parameters.py', "r")
    from parameters import I2C_SCL_PIN, I2C_SDA_PIN, UART0TX, UART0RX, UART1TX, UART1RX, UART2TX, UART2RX, TOUCH_PIN
    f.close()
except OSError:  # open failed
    print("parameter.py-file missing! Can not continue!")
    raise

try:
    f = open('runtimeconfig.json', 'r')
    with open('runtimeconfig.json') as config_file:
        data = load(config_file)
        f.close()
        SCREEN_UPDATE_INTERVAL = data['SCREEN_UPDATE_INTERVAL']
        DEBUG_SCREEN_ACTIVE = data['DEBUG_SCREEN_ACTIVE']
        SCREEN_TIMEOUT = data['SCREEN_TIMEOUT']
        TEMP_CORRECTION = data['TEMP_CORRECTION']
        RH_CORRECTION = data['RH_CORRECTION']
        PRESSURE_CORRECTION = data['PRESSURE_CORRECTION']
        DST_BEGIN_M = data['DST_BEGIN_M']         # Month
        DST_BEGIN_DAY = data['DST_BEGIN_DAY']   # Sunday = 0
        DST_BEGIN_OCC = data['DST_BEGIN_OCC']   # 1=first DST_BEGIN_DAY, 2=last
        DST_BEGIN_TIME = data['DST_BEGIN_TIME'] # Hour
        DST_END_M = data['DST_END_M']
        DST_END_DAY = data['DST_END_DAY']
        DST_END_TIME = data['DST_END_TIME']
        DST_END_OCC = data['DST_END_OCC']
        DST_TIMEZONE = data['DST_TIMEZONE']
except OSError:
    print("Runtime parameters missing. Can not continue!")
    sleep(30)
    raise


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
        "begin": (DST_BEGIN_M, DST_BEGIN_DAY, DST_BEGIN_OCC, DST_BEGIN_TIME),
            # 3 = March, 2 = last, 6 = Sunday, 3 = 03:00
        "end": (DST_END_M, DST_END_DAY, DST_END_OCC, DST_END_TIME),   # DST end  month, day, 1=first, 2=last at 04:00.
            # 10 = October, 2 = last, 6 = Sunday, 4 = 04:00
        "timezone": DST_TIMEZONE,          # hours from UTC during normal (winter time)
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


class Displayme(object):

    def __init__(self, width=16, rows=6, lpixels=128, kpixels=64):
        self.rows = []
        self.disptexts = []
        self.time = 5
        self.row = 1
        self.dispwidth = width
        self.disptext = rows
        self.pixels_width = lpixels
        self.pixels_height = kpixels
        self.screen = OLEDDISPLAY.SH1106_I2C(self.pixels_width, self.pixels_height, i2c)
        self.screentext = ""
        self.screen.poweron()
        self.screen.init_display()
        self.inverse = False

    async def long_text_to_screen(self, text, time, row=1):
        self.time = time
        self.row = row
        self.disptexts.clear()
        self.rows.clear()
        self.screentext = [text[y-self.dispwidth:y] for y in range(self.dispwidth,
                           len(text)+self.dispwidth, self.dispwidth)]
        for y in range(len(self.disptexts)):
            self.rows.append(self.disptexts[y])
        if len(self.rows) > self.disptext:
            pages = len(self.disptexts) // self.disptext
        else:
            pages = 1
        if pages == 1:
            for z in range(0, len(self.rows)):
                self.screen.text(self.rows[z], 0, self.row + z * 10, 1)

    async def text_to_row(self, text, row, time):
        self.time = time
        if len(text) > self.dispwidth:
            self.screen.text('Row too long', 0, 1 + row * 10, 1)
        elif len(text) <= self.dispwidth:
            self.screen.text(text, 0, 1 + row * 10, 1)

    async def activate_screen(self):
        self.screen.show()
        await asyncio.sleep(self.time)
        self.screen.init_display()

    async def contrast(self, contrast=255):
        if contrast > 1 or contrast < 255:
            self.screen.contrast(contrast)

    async def inverse_color(self, inverse=False):
        self.inverse = inverse
        self.screen.invert(inverse)

    async def rotate_180(self, rotate=False):
        self.screen.rotate(rotate)

    async def draw_frame(self):
        if self.inverse is False:
            self.screen.framebuf.rect(1, 1, self.pixels_width-1, self.pixels_height-1, 0xffff)
        else:
            self.screen.framebuf.rect(1, 1, self.pixels_width - 1, self.pixels_height - 1, 0x0000)

    async def draw_underline(self, row, width):
        rowheight = self.pixels_height / self.row
        startx = 1
        starty = 8 + (int(rowheight * row))
        charwidth = int(8 * width)
        if self.inverse is False:
            self.screen.framebuf.hline(startx, starty, charwidth, 0xffff)
        else:
            self.screen.framebuf.hline(startx, starty, charwidth, 0x0000)

    async def reset_screen(self):
        self.screen.reset()

    async def shut_screen(self):
        self.screen.poweroff()

    async def start_screen(self):
        self.screen.poweron()

async def show_what_i_do():
    # Output is REPL

    while True:
        print("\n1 ---------MCU------------- 1")
        print("   Memory free: %s, allocated: %s" % (gc.mem_free(), gc.mem_alloc()))
        print("   Heap info %s, hall sensor %s, raw-temp %sC" % (esp32.idf_heap_info(esp32.HEAP_DATA),
                                                                 esp32.hall_sensor(),
                                                                 "{:.1f}".format(
                                                                     ((float(esp32.raw_temperature()) - 32.0)
                                                                      * 5 / 9))))
        print("2 ---------SENSOR----------- 2")
        if not BME680_sensor_faulty:
            if (temp_average is not None) and (rh_average is not None):
                print("   Temp: %sC, Rh: %s" % (temp_average, rh_average))
            if gas_average is not None:
                print("   Gas: %s" % gas_average)
            if pressure_average is not None:
                print("   Pressure: %s" % pressure_average)
        if gps1.gps_fix_status is True:
            print("3 ---------GPS----------- 3")
            print("     Latitude: %s" % gps1.latitude)
            print("     Longitude: %s" % gps1.longitude)
            print("     Satellites: %s" % gps1.satellites)
            print("     GPSTime: %s" % gps1.gpstime)
            print("     SystemTime: %s and weekday: %s" % (resolve_date()[1], resolve_date()[2]))
        else:
            print("   Waiting GPS fix... ")
        print("\n")
        await asyncio.sleep(5)

# Adjust speed to low heat production, max 240000000, normal 160000000, min with Wi-Fi 80000000
#  freq(240000000)
freq(80000000)

i2c = SoftI2C(scl=Pin(I2C_SCL_PIN), sda=Pin(I2C_SDA_PIN))
try:
    bmes = BMESENSOR.BME680_I2C(i2c=i2c)
except OSError as e:
    raise Exception("Error: %s - BME sensor init error!" % e)

#  OLED display
try:
    display = Displayme()
except OSError as e:
    raise Exception("Error: %s - OLED Display init error!" % e)

# Touch thing
touch = TouchPad(Pin(TOUCH_PIN))

# GPS Module
# If needed, add debug= three letter NMEA code in driver (GGA/VTG/GLL/GSV/GSA/RMC)
gps1 = GPS.GPSModule(rxpin=16, txpin=17, uart=2, interval = 1, debug_gga=False, debug_gen=False, debug_rmc=False)

async def rotate_screens_loop():
    while True:
        await display.activate_screen()
        await page_1()
        await display.activate_screen()
        await page_2()
        await display.activate_screen()
        await page_3()
        await display.activate_screen()
        await page_4()
        await asyncio.sleep_ms(10)


async def read_bme680_loop():
    global temp_average
    global rh_average
    global pressure_average
    global gas_average
    temp_list = []
    rh_list = []
    press_list = []
    gas_list = []
    #  Read values from sensor once per second, add them to the array, delete oldest when size 60 (seconds)
    while True:
        try:
            temp_list.append(round(float(bmes.temperature)) + TEMP_CORRECTION)
            rh_list.append(round(float(bmes.humidity)) + RH_CORRECTION)
            press_list.append(round(float(bmes.pressure)) + PRESSURE_CORRECTION)
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
        await asyncio.sleep(1)

#  What we show on the OLED display
async def page_1():
    await display.text_to_row("%s %s" % (resolve_date()[2], resolve_date()[0]), 0, 5)
    await display.text_to_row("%s" % resolve_date()[1],1,5)
    if temp_average is None:
        await display.text_to_row("Waiting values", 2, 5)
    else:
        await display.text_to_row("Temp:%s C" % temp_average, 2, 5)
    if rh_average is None:
        await display.text_to_row("Waiting values", 3, 5)
    else:
        await display.text_to_row("Rh:%s" % rh_average, 3, 5)
    if gas_average is not None:
        await display.text_to_row("Gas:%s" % gas_average, 4, 5)
    if pressure_average is not None:
        await display.text_to_row("Pressure:%s " % pressure_average, 5, 5)
    await asyncio.sleep_ms(10)


async def page_2():
    await display.text_to_row("GPS Module 1/2", 0, 5)
    await display.text_to_row("Lat: %s" % gps1.latitude, 1, 5)
    await display.text_to_row("Lon: %s" % gps1.longitude, 2, 5)
    await display.text_to_row("Sat: %s" % gps1.satellites, 3, 5)
    await display.text_to_row("Fix: %s" % gps1.gps_fix_status, 4, 5)
    await display.text_to_row("GTi: %s" % gps1.gpstime, 5, 5)
    await asyncio.sleep_ms(10)


async def page_3():
    await display.text_to_row("GPS Module 2/2", 0, 5)
    await display.text_to_row("HDOP: %s" % gps1.hdop, 1, 5)
    await display.text_to_row("Ortho: %s" % gps1.ortho, 2, 5)
    await display.text_to_row("GeoIDS: %s" % gps1.geoids, 3, 5)
    await display.text_to_row("Speed: %s" % gps1.speed_k, 4, 5)
    await display.text_to_row("Track: %s" % gps1.trackd, 5, 5)
    await asyncio.sleep_ms(10)


async def page_4():
    await display.text_to_row("System status", 0, 5)
    await display.text_to_row("Reset cause: %s" % reset_cause(), 1, 5)
    await display.text_to_row("Memfree: %s" % gc.mem_free(), 2, 5)
    await display.text_to_row("Hall: %s" % esp32.hall_sensor(), 3, 5)
    await display.text_to_row("MCU C: %s" % ("{:.1f}".format(((float(esp32.raw_temperature())-32.0) * 5/9))), 4, 5)
    await asyncio.sleep_ms(10)


async def log_to_file_loop():
    # Executes SYNCHRONOUS code for file write if GPS is in fix and sensor values available
    while True:
        if (gps1.gps_fix_status is True) and (temp_average is not None) and (rh_average is not None) \
            and (gas_average is not None) and (pressure_average is not None):
            try:
                csv_logging()
                await asyncio.sleep(60)
            except OSError:
                # Purge oldest files
                if DEBUG_SCREEN_ACTIVE == 1:
                    print("OS Error, disc full, should not be")
        await asyncio.sleep_ms(25)


def csv_logging():
    # Checks if /data path exists. If not, create /data
    # Check if space is getting too low. IF yes, deletes oldest log file
    # Note! Not asynchronous!

    file_dates = []

    try:
        os.listdir('/data')
    except OSError:
        os.mkdir('/data')

    filename = "/data/val-%s.csv" %str(resolve_date()[0].replace('.',''))  # file changed every day

    try:
        with open(filename, 'a+') as logf:
            try:
                logf.write("%s" % str(resolve_date()[0])) # Date in local format
                logf.write(",")
                logf.write("%s" % str(resolve_date()[1])) # Localtime (not GMT/UTC)
                logf.write(",")
                logf.write(str(temp_average))
                logf.write(",")
                logf.write(str(rh_average))
                logf.write(",")
                logf.write(str(pressure_average))
                logf.write(",")
                logf.write(str(gas_average))
                logf.write(",")
                logf.write(str(gps1.latitude))
                logf.write(",")
                logf.write(str(gps1.longitude))
                logf.write(",")
                logf.write(str(gps1.satellites))
                logf.write(",")
                logf.write(str(gps1.ortho))
                logf.write(",")
                logf.write(str(gps1.geoids))
                logf.write(",")
                logf.write(str(gps1.speed_k))
                logf.write("\r\n")
            except OSError as e:
                print('OSError %s' % e)
                raise OSError
    except OSError as e:
        print('OSError %s' %e )
        raise OSError
    logf.close()
    if DEBUG_SCREEN_ACTIVE == 1:
        print("4 ---------OS----------- 4")
        print("Succesfull write to file %s" %filename)

    blocksize = os.statvfs('/')[0]
    freeblock = os.statvfs('/')[3]
    if DEBUG_SCREEN_ACTIVE == 1:
        print("Space left: %s" % (freeblock * blocksize))

    if (blocksize * freeblock) < 50000:
        # Delete oldest file
        list_of_files = os.listdir('/data')
        full_path = ["data/{0}".format(x) for x in list_of_files]
        for y in range (len(full_path)):
            file_dates.append((os.stat(full_path[y])[9], full_path[y]))   # last value is st_ctime
            # file_dates[time][filename]
        file_dates.sort()
        oldest_file = file_dates[0][1]
        if DEBUG_SCREEN_ACTIVE == 1:
            print("Deleting oldest file: %s" %oldest_file)
        os.remove(oldest_file)

async def main():
    loop = asyncio.get_event_loop()
    if DEBUG_SCREEN_ACTIVE == 1:
        loop.create_task(show_what_i_do())
    loop.create_task(read_bme680_loop())
    loop.create_task(gps1.read_async_loop())
    loop.create_task(rotate_screens_loop())
    loop.create_task(log_to_file_loop())
    loop.run_forever()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except MemoryError:
        reset()
