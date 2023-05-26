"""
  24.05.2025: Jari Hiltunen

  For asyncronous StreamReader by Divergentti / Jari Hiltunen
  Add loop into your code loop.create_task(objectname.read_async_loop())
  NEO-6M datasheet https://content.u-blox.com/sites/default/files/products/documents/NEO-6_DataSheet_%28GPS.G6-HW-09005%29.pdf

  Protocol: NMEA including GSV, RMC, GSA, GGA, GLL, VTG, TXT

    GP = for GPS codes
    BD or GB - Beidou,GA - Galileo, GL - GLONASS.

"""

from machine import UART
import time
import uasyncio as asyncio
import gc

# This list is about all, you could shrink to Neo6M GSV, RMC, GSA, GGA, GLL, VTG, TXT
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
    def __init__(self, rxpin=16, txpin=17, uart=2, interval=3, settime=True, debug = False):
        self.moduleUart = UART(uart, 9600, 8, None, 1, rx=rxpin, tx=txpin)
        self.moduleUart.init()
        self.read_interval = interval
        self.gps_fix_status = False
        self.latitude = ""
        self.longitude = ""
        self.satellites = ""
        self.GPStime = ""
        self.debug = debug
        self.readtime =  time.time()
        self.readdata = ""
        self.foundcode = ""
        self.settime = settime

    @staticmethod
    def checksum(nmeaword):
        linebegin = nmeaword.find(b'$')
        cksumlenght = nmeaword.find(b'\r\n')
        cksumbegin = nmeaword.rfind(b'*')
        if linebegin == -1:
            return "Not found"
        if cksumbegin == -1:
            return "Not found"
        if cksumlenght == -1:
            return "Not found"
        # to be XORed
        cksum = str(nmeaword[cksumbegin+1:cksumlenght].decode("utf-8"))   # cksum in nmeaword
        chksumdata = nmeaword[linebegin+1:cksumbegin].decode("utf-8")  # stripped nmeaword
        csum = 0
        for c in chksumdata:
            csum ^= ord(c)
        if hex(csum) == hex(int(cksum,16)):
            return True
        else:
            return False

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
        datain = ""
        port = asyncio.StreamReader(self.moduleUart)
        try:
            datain = await port.readline()
        except TimeoutError:
            self.moduleUart.init()
        try:
            self.checksum(datain)
        except ValueError:
            self.readdata = "Bad formed"
            return False
        except False:
            if self.debug is True:
                print ("Bad formed")
            self.readdata = "Bad formed"
            return False
        return datain.decode("utf-8")


    async def read_async_loop(self):

        while True:
            if (time.time() - self.readtime) >= self.read_interval:
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
                    # 0 = Message ID $GPGGA
                    # 1=  UTC of position fix
                    # 2 = Latitude
                    # 3 = Direction of latitude: N: North, S: South
                    # 4 = Longitude
                    # 5 = Direction of longitude: E: East, W: West
                    # 6 = GPS Quality indicator: 0: Fix not valid, 1: GPS fix, 2: Differential GPS fix (DGNSS), SBAS, OmniSTAR VBS, Beacon, RTX in GVBS mode, 3: Not applicable
                    #     4: RTK Fixed, xFill, 5: RTK Float, OmniSTAR XP/HP, Location RTK, RTX, 6: INS Dead reckoning
                    # 7 = Number of SVs in use, range from 00 through to 24+
                    # 8 = HDOP
                    # 9 = Orthometric height (MSL reference)
                    # 10 = M: unit of measure for orthometric height is meters
                    # 11 = Geoid separation
                    # 12 = M: geoid separation measured in meters
                    # 13 = Age of differential GPS data record, Type 1 or Type 9. Null field when DGPS is not used.
                    # 14 = Reference station ID, range 0000 to 4095. A null field when any reference station ID is selected and no corrections are received. See table below for a description of the field values.
                    # 15 = The checksum data, always begins with *
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
                if self.foundcode == 'GPVTG':
                    # 0 = Message ID $GPVTG
                    # 1 = Track made good (degrees true)
                    # 2 = T: track made good is relative to true north
                    # 3 = Track made good (degrees magnetic)
                    # 4 = M: track made good is relative to magnetic north
                    # 5 = Speed, in knots
                    # 6 = N: speed is measured in knots
                    # 7 = Speed over ground in kilometers/hour (kph)
                    # 8 = K: speed over ground is measured in kph
                    # 9 = Mode indicator: A: Autonomous mode,  D: Differential mode, E: Estimated (dead reckoning) mode,  M: Manual Input mode, S: Simulator mode, N: Data not valid
                    # 10 = The checksum data, always begins with *
                    parts = self.readdata.split(',')
                    if self.debug is True:
                        print("GPVTG: %s" %parts)
                        print("---")
                if self.foundcode == 'GPGLL':
                    # 0 = Message ID $GPGLL, 1 = Latitude in dd mm,mmmm format (0-7 decimal places)
                    # 2 = Direction of latitude N: North S: South
                    # 3 = Longitude in ddd mm,mmmm format (0-7 decimal places)
                    # 4 = Direction of longitude E: East W: West
                    # 5 = UTC of position in hhmmss.ss format
                    # 6 = Status indicator: A: Data valid, V: Data not valid
                    # 7 = The checksum data, always begins with *
                    #
                    # Mode indicator:
                    # A: Autonomous mode
                    # D: Differential mode
                    # E: Estimated (dead reckoning) mode
                    # M: Manual input mode
                    # S: Simulator mode
                    # N: Data not valid
                    parts = self.readdata.split(',')
                    if self.debug is True:
                        print("GPGLL parts: %s" %parts)
                        print("---")
                if self.foundcode == 'GPGSV':
                    # NMEA-0183 message:
                    # 1 = Total number of messages of this type in this cycle,2 = Message number,
                    # 3 = Total number of SVs in view
                    # 4 = SV PRN number, 5= Elevation in degrees, 90 maximum, 6 = Azimuth, dg from true north
                    # 7 = SNR, 00-99 dB,8-19 = Information about SVs'
                    parts = self.readdata.split(',')
                    if self.debug is True:
                        print("GPGSV parts %s: " %parts)
                        print("---")
                if self.foundcode == 'GPGSA':
                    # 1= Mode:M=Manual, forced to operate in 2D or 3D, A=Automatic, 3D/2D
                    # 2= Mode: 1=Fix not available, 2=2Dm 3=3D
                    # 3-6 = IDs of SVs, PDOP,HDOP and VDOP
                    # 7 = The checksum data, always begins with * (NMEA-0183 version 4.10 GPS/GLonass etc)
                    parts = self.readdata.split(',')
                    if self.debug is True:
                        print("GPGSA: %s" % parts)
                        print("---")
                if self.foundcode == 'GPRMC':
                    # 1 = UTC of position fix, 2= Status A=active or V=void,3 = Latitude
                    # 4 = Longitude, 5 = Speed over the ground in knots, 6 = Track angle in degrees (True)
                    # 7 = Date, 8= Magnetic variation, in degrees
                    # 9 = The checksum data, always begins with *
                    parts = self.readdata.split(',')
                    if self.debug is True:
                        print("GPRMC: %s" %parts)
                        print("---")
            await asyncio.sleep_ms(100)
