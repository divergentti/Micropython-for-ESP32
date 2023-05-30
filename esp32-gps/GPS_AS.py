"""
  30.05.2023: Jari Hiltunen, version 0.3
  - added system date and time set from satellite using GPRMC (if constructor self_settime = True)
  - reworked the reader part


  For asynchronous StreamReader by Divergentti / Jari Hiltunen
  Add loop into your code loop.create_task(objectname.read_async_loop())
  Tested UBX-G60xx ROM CORE 6.02 (36023) Oct 15 2009
  NEO-6M datasheet https://content.u-blox.com/sites/default/files/products/documents/NEO-6_DataSheet_%28GPS.G6-HW-09005%29.pdf
  u-blox 6 Receiver Description Including Protocol Specification:
  https://content.u-blox.com/sites/default/files/products/documents/u-blox6_ReceiverDescrProtSpec_%28GPS.G6-SW-10018%29_Public.pdf

  Time-To-First-Fix 26 seconds after cold start, 1 seconds warm start
  Maximum update rate 5 Hz
  Accuracy 2.5 meters

  Protocol: NMEA including GSV, RMC, GSA, GGA, GLL, VTG, TXT
  NMEA codes at https://www.nmea.org/

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

    For debugging:
    - debug_gen is about general read etc
    - debug_gga Global Positioning System Fix Data
    - debug_vtg Track Made Good and Ground Speed
    - debug_gll Geographic Position, Latitude/Longitude
    - debug_gsv GPS Satellites in view
    - debug_gsa GPS DOP and active satellites
    - debug_rmc = Recommended minimum specific GPS/Transit data

    Setting system time is done via GPRMC receive. During object init default is set_time = True
    Important!
        - self.gpstime is read from GGA! Do not use that value for setting time, because it may be not correct!
        - weekday number is not updated unless it is set before object init!
"""

from machine import UART, RTC
import time
import uasyncio as asyncio
import gc

rtc_clock = RTC()
start_code = '$'
system_code = 'GP'

class GPSModule:
    #  Default UART2, rx=9, tx=10, readinterval = 1 seconds. Avoid UART1.
    def __init__(self, rxpin=16, txpin=17, uart=2, interval=1, timeout = 60, set_time= True, debug_gen=False,
                 debug_gga = False, debug_vtg = False, debug_gll = False, debug_gsv=False,
                 debug_gsa=False, debug_rmc = False):
        self.moduleUart = UART(uart, 9600, 8, None, 1, rx=rxpin, tx=txpin)
        self.moduleUart.init()
        self.read_interval = interval
        self.timeout = timeout
        self.set_time = set_time
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
        self.data_valid = False
        self.spd_o_g = ""
        self.course_o_g = ""
        self.ddmmyy = ""
        self.debug_gen = debug_gen
        self.debug_gga = debug_gga
        self.debug_vtg = debug_vtg
        self.debug_gll = debug_gll
        self.debug_gsv = debug_gsv
        self.debug_gsa = debug_gsa
        self.debug_rmc = debug_rmc
        self.readtime =  time.time()
        self.readdata = bytearray(255)
        self.foundcode = bytearray(6)

    @staticmethod
    def weekday(yday, year):
        wkd = 7%(7%yday+year+year(year-1)/4-1)
        return wkd

    @staticmethod
    def checksum(nmeaword):
        linebegin = nmeaword.find(bytes(start_code, 'UTF-8'))
        cksumlenght = nmeaword.find(b'\r\n')
        cksumbegin = nmeaword.rfind(b'*')
        if linebegin == -1:
            return False
        if cksumbegin == -1:
            return False
        if cksumlenght == -1:
            return False
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
    def convert_to_degree(rawdegrees):
        rawasfloat = float(rawdegrees)
        firstdigits = int(rawasfloat / 100)
        nexttwodigits = rawasfloat - float(firstdigits * 100)
        converted = float(firstdigits + nexttwodigits / 60.0)
        converted = '{0:.6f}'.format(converted)
        return str(converted)


    async def reader(self):
        port = asyncio.StreamReader(self.moduleUart)
        try:
            datain = await port.readline()
        except MemoryError:
            return False
        if self.checksum(datain) is True:
            self.readdata = datain
            self.readtime = time.time()
            pos = datain.find(bytes(start_code + system_code,'UTF-8'))
            if pos == -1:
                return False
            else:
                self.foundcode = datain[pos + 3: pos + 6]
                decoded_data = str(self.readdata.decode('utf-8'))
                self.readdata = decoded_data.split(',')
            if self.debug_gen is True:
                print("Found code: %s and read data is: %s" %(self.foundcode, self.readdata))
            return True
        else:
            return False

    async def read_async_loop(self):

        while True:
            if (time.time() - self.readtime) >= self.read_interval:
                await self.reader()

                if self.foundcode == b'GGA':
                    if len(self.readdata) == 15:
                        try:
                            self.latitude = self.convert_to_degree(self.readdata[2])
                        except ValueError:
                            continue
                        if self.readdata[3] == 'S':
                            self.latitude = "-" + self.latitude
                        try:
                            self.longitude = self.convert_to_degree(self.readdata[4])
                        except ValueError:
                            continue
                        if self.readdata[5] == 'W':
                            self.longitude = "-" + self.longitude
                        self.quality_indicator = self.readdata[6]
                        self.satellites = self.readdata[7]
                        self.gpstime = self.readdata[1][0:2] + ":" + self.readdata[1][2:4] + ":" + self.readdata[1][4:6]
                        self.hdop = self.readdata[8]
                        self.ortho = self.readdata[9]
                        self.ortho_u = self.readdata[10]
                        self.geoids = self.readdata[11]
                        self.geoids_m = self.readdata[12]
                        if int(self.quality_indicator) == 0:
                            self.gps_fix_status = False
                        else:
                            self.gps_fix_status = True
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
                if self.foundcode == b'VTG':
                    if len(self.readdata) == 10:
                        self.trackd = self.readdata[1]
                        self.trackg_n = self.readdata[2]
                        self.trackg_deg = self.readdata[3]
                        self.trackg_deg_n = self.readdata[4]
                        self.speed_k = self.readdata[5]
                        self.speed_k_t = self.readdata[6]
                        self.gspeed = self.readdata[7]
                        self.gspeed_k = self.readdata[8]
                        self.vtgmode = self.readdata[9]
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

                if self.foundcode == b'GLL':
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

                    if len(self.readdata) == 7:
                        if self.debug_gll is True:
                            print("--- GLL not implemented ---")
                if self.foundcode == b'GSV':
                    # NMEA-0183 message:
                    # 1 = Total number of messages of this type in this cycle,2 = Message number,
                    # 3 = Total number of SVs in view
                    # 4 = SV PRN number, 5= Elevation in degrees, 90 maximum, 6 = Azimuth, dg from true north
                    # 7 = SNR, 00-99 dB,8-19 = Information about SVs'
                    if len(self.readdata) == 7:
                        if self.debug_gsv is True:
                            print("--- GSV not implemented ---")
                if self.foundcode == b'GSA':
                    # 1= Mode:M=Manual, forced to operate in 2D or 3D, A=Automatic, 3D/2D
                    # 2= Mode: 1=Fix not available, 2=2Dm 3=3D
                    # 3-6 = IDs of SVs, PDOP,HDOP and VDOP
                    if len(self.readdata) == 7:
                        if self.debug_gsa is True:
                            print("--- GSA not implemented ---")
                if self.foundcode == b'RMC':
                    if len(self.readdata) == 13:
                        gpstime_h = int(self.readdata[1][0:2])
                        gpstime_m = int(self.readdata[1][2:4])
                        gpstime_s = int(self.readdata[1][4:6])
                        if self.readdata[2] =='V':
                            self.data_valid = False
                        if self.readdata[2] == 'A':
                            self.data_valid = True
                        try:
                            self.latitude = self.convert_to_degree(self.readdata[3])
                        except ValueError:
                            continue
                        if self.readdata[4] == 'S':
                            self.latitude = "-" + self.latitude
                        try:
                            self.longitude = self.convert_to_degree(self.readdata[5])
                        except ValueError:
                            continue
                        if self.readdata[6] == 'W':
                            self.longitude = "-" + self.longitude
                        self.spd_o_g = self.readdata[7]
                        self.course_o_g = self.readdata[8]
                        self.ddmmyy = self.readdata[9]
                        if self.set_time is True and self.data_valid is True:
                            year = int('20'+ self.ddmmyy[4:6])
                            month = int(self.ddmmyy[2:4])
                            date = int(self.ddmmyy[0:2])
                            locatimenow = time.localtime()
                            weekday = int(locatimenow[6])
                            # TO BE IMPLEMENTED! Needs YEAR TO DATE
                            # weekday = self.weekday(ydate, year)
                            rtc_clock.datetime((year,month,date, weekday, gpstime_h, gpstime_m, gpstime_s,0))
                        if self.debug_rmc is True:
                            print("--- RMC debug ---")
                            print("GPSTime: %s" % self.gpstime)
                            print("System time set: ", time.localtime())
                            print("Data valid %s:" %self.data_valid)
                            print("Speed over ground: %s" %self.spd_o_g)
                            print("Course over ground: %s" %self.course_o_g)
                            print("--- End of RMC ---")
                gc.collect()
            await asyncio.sleep_ms(25)
