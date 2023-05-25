"""
  25.05.2023: Jari Hiltunen

  For asyncronous StreamReader by Divergentti / Jari Hiltunen
  Add loop into your code loop.create_task(objectname.read_async_loop())
  Borrowed code from https://microcontrollerslab.com/neo-6m-gps-module-esp32-micropython/

    GP = for GPS codes
    BD or GB - Beidou,GA - Galileo, GL - GLONASS.

Undergoing testing!
"""

from machine import UART
from utime import time
import uasyncio as asyncio
import gc

GPcodes = [['GPAAM', 'Waypoint Arrival Alarm'], ['GPALM', 'GPS Almanac Data'], ['GPAPA', 'Autopilot Sentence "A"'],
['GPAPB', 'Autopilot Sentence "B"'], ['GPASD', 'Autopilot System Data'],
['GPBEC', 'Bearing & Distance to Waypoint, Dead Reckoning'], ['GPBOD', 'Bearing, Origin to Destination'],
['GPBWC', 'Bearing & Distance to Waypoint, Great Circle'], ['GPBWR', 'Bearing & Distance to Waypoint, Rhumb Line'],
['GPBWW', 'Bearing, Waypoint to Waypoint'], ['GPDBT', 'Depth Below Transducer'], ['GPDCN', 'Decca Position'],
['GPDPT', 'Depth'], ['GPFSI', 'Frequency Set Information'], ['GPGGA', 'Global Positioning System Fix Data'],
['GPGLC', 'Geographic Position, Loran'], ['GPGLL', 'Geographic Position, Latitude/Longitude'],
['GPGSA', 'GPS DOP and Active Satellites'], ['GPGSV', 'GPS Satellites in View'], ['GPGXA', 'TRANSIT Position'],
['GPHDG', 'Heading, Deviation & Variation'], ['GPHDT', 'Heading, True'], ['GPHSC', 'Heading Steering Command'],
['GPLCD', 'Loran C Signal Data'], ['GPMTA', 'Air Temperature (to be phased out)'], ['GPMTW', 'Water Temperature'],
['GPMWD', 'Wind Direction'], ['GPMWV', 'Wind Speed and Angle'], ['GPOLN', 'Omega Lane Numbers'],
['GPOSD', 'Own Ship Data'], ['GPR00', 'Waypoint active route (not standard)'],
['GPRMA', 'Recommended Minimum Specific Loran C Data'], ['GPRMB', 'Recommended Minimum Navigation Information'],
['GPRMC', 'Recommended Minimum Specific GPS/TRANSIT Data'], ['GPROT', 'Rate of Turn'],
['GPRPM', 'Revolutions'], ['GPRSA', 'Rudder Sensor Angle'], ['GPRSD', 'RADAR System Data'],
['GPRTE', 'Routes'], ['GPSFI', 'Scanning Frequency Information'], ['GPSTN', 'Multiple Data ID'],
['GPTXT', 'Text'],
['GPTRF', 'Transit Fix Data'], ['GPTTM', 'Tracked Target Message'], ['GPVBW', 'Dual Ground/Water Speed'],
['GPVDR', 'Set and Drift'], ['GPVHW', 'Water Speed and Heading'], ['GPVLW', 'Distance Traveled through the Water'],
['GPVPW', 'Speed, Measured Parallel to Wind'], ['GPVTG', 'Track Made Good and Ground Speed'],
['GPWCV', 'Waypoint Closure Velocity'], ['GPWNC', 'Distance, Waypoint to Waypoint'], ['GPWPL', 'Waypoint Location'],
['GPXDR', 'Transducer Measurements'], ['GPXTE', 'Cross' , 'Track Error, Measured'],
['GPXTR', 'Cross' , 'Track Error, Dead Reckoning'], ['GPZDA', 'Time & Date'],
['GPZFO', 'UTC & Time from Origin Waypoint'], ['GPZTG', 'UTC & Time to Destination Waypoint']]
# GPcodes[-code][text related to code]
start_code = '$'

class GPSModule:
    #  Default UART2, rx=9, tx=10, readinterval = 3 seconds. Avoid UART1.
    def __init__(self, rxpin=16, txpin=17, uart=2, interval=3, debug = False):
        self.moduleUart = UART(uart, 9600, 8, None, 1, rx=rxpin, tx=txpin)
        self.moduleUart.init()
        self.read_interval = interval
        self.gps_fix_status = False
        self.latitude = ""
        self.longitude = ""
        self.satellites = ""
        self.GPStime = ""
        self.debug = debug
        self.readtime =  time()
        self.readdata = ""
        self.foundcode = ""

    @staticmethod
    def convertToDegree(rawdegrees):
        rawasfloat = float(rawdegrees)
        firstdigits = int(rawasfloat / 100)
        nexttwodigits = rawasfloat - float(firstdigits * 100)
        converted = float(firstdigits + nexttwodigits / 60.0)
        converted = '{0:.6f}'.format(converted)
        return str(converted)

    @staticmethod
    def findgpscode(stringin):
        pos = stringin.find(start_code)
        if pos == -1:
            return "Not found"
        else:
            return stringin[pos+1:pos+6]
    async def reader(self):
        port = asyncio.StreamReader(self.moduleUart)
        data = await port.readline()
        if len(data) >6:
            self.readtime = time()
            return data
        else:
            return "too short"

    async def read_async_loop(self):

        while True:
            if (time() - self.readtime) >= self.read_interval:
                gc.collect()
                try:
                    self.readdata = str(await self.reader())
                except MemoryError:
                    continue
                try:
                    self.foundcode =self.findgpscode(self.readdata)
                except ValueError:
                    continue
                if self.debug is True:
                    for i in range (len(GPcodes)):
                        if self.foundcode == GPcodes[i][0]:
                            print("Code: %s = %s" % (self.foundcode, GPcodes[i][1]))
                if self.foundcode == 'GPGGA':
                    parts = self.readdata.split(',')
                    if len(parts) == 15:
                        try:
                            self.latitude = self.convertToDegree(parts[2])
                        except ValueError:
                            continue
                        if (parts[3] == 'S'):
                            self.latitude = "-" + self.latitude
                        try:
                            self.longitude = self.convertToDegree(parts[4])
                        except ValueError:
                            continue
                        if (parts[5] == 'W'):
                            self.longitude = "-" + self.longitude
                        self.satellites = parts[7]
                        self.GPStime = parts[1][0:2] + ":" + parts[1][2:4] + ":" + parts[1][4:6]
                        self.gps_fix_status = True

            await asyncio.sleep_ms(100)
