"""
  29.05.2023: Jari Hiltunen, version 0.1

  For asynchronous StreamReader by Divergentti / Jari Hiltunen
  Add loop into your code loop.create_task(objectname.read_async_loop())
  Tested UBX-G60xx ROM CORE 6.02 (36023) Oct 15 2009
  NEO-6M datasheet https://content.u-blox.com/sites/default/files/products/documents/NEO-6_DataSheet_%28GPS.G6-HW-09005%29.pdf

  Time-To-First-Fix 26 seconds after cold start, 1 seconds warm start
  Maximum update rate 5 Hz
  Accuracy 2.5 meters

  Protocol: NMEA including GSV, RMC, GSA, GGA, GLL, VTG, TXT

    GP = for GPS codes
    BD or GB - Beidou,GA - Galileo, GL - GLONASS.

  Usage:
        import drivers.GPS_AS as GPS
        gps1 = GPS.GPSModule(rxpin=16, txpin=17, uart=2, interval = 3)

        .. your async code, which access values of the gps1 object, such as gps1.gpstime ...

        async def main():
            loop = asyncio.get_event_loop()
            loop.create_task(gps1.read_async_loop())
            loop.run_forever()

        if __name__ == "__main__":
        try:
            asyncio.run(main())
        except MemoryError:
            reset()

    For debugging: debug_gen=False, debug_gga = False, debug_vtg = False, debug_gll = False, debug_gsv=False,
        debug_gsa=False, debug_rmc = False
     - debug_gen is about general read etc
    - debug_gga Global Positioning System Fix Data
    - debug_vtg Track Made Good and Ground Speed
    - debug_gll Geographic Position, Latitude/Longitude
    - debug_gsv GPS Satellites in view
    - debug_gsa GPS DOP and active satellites
    - debug_rmc = Recommended minimum specific GPS/Transit data 

"""

from machine import UART
import time
import uasyncio as asyncio
import gc

start_code = '$'
system_code = 'GP'

class GPSModule:
    #  Default UART2, rx=9, tx=10, readinterval = 1 seconds. Avoid UART1.
    def __init__(self, rxpin=16, txpin=17, uart=2, interval=1, timeout = 60, debug_gen=False,
                 debug_gga = False, debug_vtg = False, debug_gll = False, debug_gsv=False,
                 debug_gsa=False, debug_rmc = False):
        self.moduleUart = UART(uart, 9600, 8, None, 1, rx=rxpin, tx=txpin)
        self.moduleUart.init()
        self.read_interval = interval
        self.timeout = timeout
        self.gps_fix_status = False
        self.latitude = ""
        self.longitude = ""
        self.quality_indicator = ""
        self.satellites = ""
        self.gpstime = ""
        self.hdop = ""
        self.ortho=""
        self.ortho_u = ""
        self.geoids = ""
        self.geoids_m =""
        self.trackd = ""
        self.trackg_n = ""
        self.trackg_deg = ""
        self.trackg_deg_n = ""
        self.speed_k = ""
        self.speed_k_t = ""
        self.gspeed = ""
        self.gspeed_k = ""
        self.vtgmode = ""
        self.debug_gen = debug_gen
        self.debug_gga = debug_gga
        self.debug_vtg = debug_vtg
        self.debug_gll = debug_gll
        self.debug_gsv = debug_gsv
        self.debug_gsa = debug_gsa
        self.debug_rmc = debug_rmc
        self.readtime =  time.time()
        self.readdata = ""
        self.foundcode = ""



    @staticmethod
    def checksum(nmeaword):
        linebegin = nmeaword.find(bytes(start_code, 'UTF-8'))
        cksumlenght = nmeaword.find(b'\r\n')
        cksumbegin = nmeaword.rfind(b'*')
        if linebegin == -1:
            return "Not found line begin"
        if cksumbegin == -1:
            return "Not found checksum begin"
        if cksumlenght == -1:
            return "Not found checksum length"
        # to be XORed
        cksum = str(nmeaword[cksumbegin+1:cksumlenght].decode("utf-8"))   # cksum in nmeaword
        chksumdata = nmeaword[linebegin+1:cksumbegin].decode("utf-8")  # stripped nmeaword
        csum = 0
        for c in chksumdata:
            csum ^= ord(c)
        if hex(csum) == hex(int(cksum,16)):
            return chksumdata
        else:
            return "CRCError"

    @staticmethod
    def convert_to_degree(rawdegrees):
        rawasfloat = float(rawdegrees)
        firstdigits = int(rawasfloat / 100)
        nexttwodigits = rawasfloat - float(firstdigits * 100)
        converted = float(firstdigits + nexttwodigits / 60.0)
        converted = '{0:.6f}'.format(converted)
        return str(converted)

    @staticmethod
    def findgpscode(stringin):
        if len(stringin) < 9:
            return "Too short"
        pos = stringin.find(start_code+system_code)
        if pos == -1:
            return "Not found: %s" %start_code+system_code
        else:
            return stringin[pos+3:pos+6]

    async def reader(self):
        port = asyncio.StreamReader(self.moduleUart)
        try:
            datain = await port.readline()
        except MemoryError as error:
            return "Reader error: %s" %error
        try:
            self.readdata = self.checksum(datain)
        except ValueError as error:
            return "Reader error: %s" %error
        except False:
            return "Reader: Bad formed"
        if self.debug_gen is True:
            print("Data read: %s" %self.readdata)
        self.readtime = time.time()
        return start_code+self.readdata


    async def read_async_loop(self):

        while True:
            if (time.time() - self.readtime) >= self.read_interval:
                try:
                    self.readdata = str(await self.reader())
                except MemoryError as error:
                    if self.debug_gen is True:
                        print("Readdata error %s" % error)
                    continue
                try:
                    self.foundcode =self.findgpscode(self.readdata)
                except ValueError as error:
                    if self.debug_gen is True:
                        print("Found error %s" % error)
                    continue

                if self.foundcode == 'GGA':
                    parts = self.readdata.split(',')
                    if len(parts) == 15:
                        try:
                            self.latitude = self.convert_to_degree(parts[2])
                        except ValueError:
                            continue
                        if parts[3] == 'S':
                            self.latitude = "-" + self.latitude
                        try:
                            self.longitude = self.convert_to_degree(parts[4])
                        except ValueError:
                            continue
                        if parts[5] == 'W':
                            self.longitude = "-" + self.longitude
                        self.quality_indicator = parts[6]
                        self.satellites = parts[7]
                        self.gpstime = parts[1][0:2] + ":" + parts[1][2:4] + ":" + parts[1][4:6]
                        self.hdop = parts[8]
                        self.ortho = parts[9]
                        self.ortho_u = parts[10]
                        self.geoids = parts[11]
                        self.geoids_m = parts[12]
                        if int(self.quality_indicator) == 1 or int(self.quality_indicator) ==2:
                            self.gps_fix_status = True
                        else:
                            self.gps_fix_status = False
                        if self.debug_gga is True:
                            print("--- Debug GGA ---")
                            print("Latitude: %s" % self.latitude )
                            print("Longitude: %s" % self.longitude)
                            print("Satellites: %s" % self.satellites)
                            print("Time: %s" % self.gpstime)
                            print("Fix: %s" % self.gps_fix_status)
                            print("Quality indicator: %s" %self.quality_indicator)
                            print("Horizontal Dilution of Precision: %s" % self.hdop)
                            print("Orthometric height %s %s:" % (self.ortho, self.ortho_u))
                            print("Height of geoid above WGS84 ellipsoid: %s %s" % (self.geoids, self.geoids_m))
                            print("--- end of GGA ---")
                if self.foundcode == 'VTG':
                    parts = self.readdata.split(',')
                    if len(parts) == 10:
                        self.trackd = parts[1]
                        self.trackg_n = parts[2]
                        self.trackg_deg = parts[3]
                        self.trackg_deg_n = parts[4]
                        self.speed_k = parts[5]
                        self.speed_k_t = parts[6]
                        self.gspeed = parts[7]
                        self.gspeed_k = parts[8]
                        self.vtgmode = parts[9]
                        if self.debug_vtg is True:
                            print("--- VTG debug --- ")
                            print("Track made good (degrees true): %s" % self.trackd)
                            print("T: track made good is relative to true north: %s:" % self.trackg_n)
                            print("Track made good (degrees magnetic): %s" % self.trackg_deg)
                            print("M: track made good is relative to magnetic north: %s" % self.trackg_deg_n)
                            print("Speed, in knots: %s" % self.speed_k)
                            print("N: speed is measured in knots: %s" % self.speed_k_t)
                            print("Speed over ground in kilometers/hour (kph): %s" % self.gspeed)
                            print("K: speed over ground is measured in kph: %s" % self.gspeed_k)
                            print("Mode indicator: %s" % self.vtgmode)
                            print("--- end of VTG ---")

                if self.foundcode == 'GLL':
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
                    if len(parts) == 7:
                        if self.debug_gll is True:
                            print("--- GLL not implemented ---")
                if self.foundcode == 'GSV':
                    # NMEA-0183 message:
                    # 1 = Total number of messages of this type in this cycle,2 = Message number,
                    # 3 = Total number of SVs in view
                    # 4 = SV PRN number, 5= Elevation in degrees, 90 maximum, 6 = Azimuth, dg from true north
                    # 7 = SNR, 00-99 dB,8-19 = Information about SVs'
                    parts = self.readdata.split(',')
                    if len(parts) == 7:
                        if self.debug_gsv is True:
                            print("--- GSV not implemented ---")
                if self.foundcode == 'GSA':
                    # 1= Mode:M=Manual, forced to operate in 2D or 3D, A=Automatic, 3D/2D
                    # 2= Mode: 1=Fix not available, 2=2Dm 3=3D
                    # 3-6 = IDs of SVs, PDOP,HDOP and VDOP
                    # 7 = The checksum data, always begins with * (NMEA-0183 version 4.10 GPS/GLonass etc)
                    parts = self.readdata.split(',')
                    if len(parts) == 7:
                        if self.debug_gsa is True:
                            print("--- GSA not implemented ---")
                if self.foundcode == 'RMC':
                    # 1 = UTC of position fix, 2= Status A=active or V=void,3 = Latitude
                    # 4 = Longitude, 5 = Speed over the ground in knots, 6 = Track angle in degrees (True)
                    # 7 = Date, 8= Magnetic variation, in degrees
                    # 9 = The checksum data, always begins with *
                    parts = self.readdata.split(',')
                    if len(parts) == 9:
                        if self.debug_rmc is True:
                            print("--- RMC not implemented ---")
                if (time.time() - self.readtime) > self.timeout:
                    self.moduleUart.init()
                    if self.debug_gen is True:
                        print("Timed out, UART init!")
                    self.moduleUart.init()
                gc.collect()
            await asyncio.sleep_ms(25)
