"""
  For asynchronous StreamReader by Divergentti / Jari Hiltunen

  Version 0.4. Updated 31.5.2023.

  Changelog:
  - 28.5.2023: initial version idea from Microcontrollers Lab article "NEO-6M GPS Module with ESP32 using MicroPython"
  - 30.5.2023: added system date and time set from satellite using GPRMC (if constructor self_settime = True)
  - 30.5.2023: reworked the reader part
  - 31.5.2023: added weekday calculation for setting system time from satellite
  - 31.5.2023: code test ongoing ... 

  Tested: ESP32 with esp32-ota-20230426-v1.20.0.bin micropython & OLED display & BME680 & Neo6M GPS module
  Neo 6M module: UBX-G60xx ROM CORE 6.02 (36023) Oct 15 2009 (Datasheets and Receiver Description available)

  Protocol: NMEA including GSV, RMC, GSA, GGA, GLL, VTG, TXT.
    GP = for GPS codes. BD or GB = Beidou, GA = Galileo, GL = GLONASS.

  Usage @ main.py:
        import drivers.GPS_AS as GPS
        gps1 = GPS.GPSModule(rxpin=16, txpin=17, uart=2, interval = 3)

        .. your async code, which access values of the gps1 object, such as gps1.gpstime ...gps1.latitude ...

        async def main():
            loop = asyncio.get_event_loop()
            loop.create_task(gps1.read_async_loop())
            loop.run_forever()

        if __name__ == "__main__":
        try:
            asyncio.run(main())
        except MemoryError:
            reset()

    For debugging options: see constructor.
    During object init default is set_time = True, which means system time (RTC) is set from the satellite time.
    Setting system time is done via GPRMC NMEA receive.

    Important note!
        - self.gpstime is read from GGA! Do not use setting system time, because it is not updated frequently!
        - longitude and latitude is set from GGA, not from RMC
"""

from machine import UART, RTC
import time
import uasyncio as asyncio
import gc

rtc_clock = RTC()  # for setting up system time (ticks from epoc)
start_code = '$'   # starting code in the NMEA message
system_code = 'GP' # GPS

class GPSModule:
    #  Default UART2, rx=16, tx=17, readinterval = 1 seconds. Avoid UART1. debug_gen is general debug.
    def __init__(self, rxpin=16, txpin=17, uart=2, interval=1, set_time= True, debug_gen=False,
                 debug_gga = False, debug_vtg = False, debug_gll = False, debug_gsv=False,
                 debug_gsa=False, debug_rmc = False):
        self.moduleUart = UART(uart, 9600, 8, None, 1, rx=rxpin, tx=txpin)
        self.moduleUart.init()
        self.read_interval = interval # module can do 5Hz, but UART may be problem
        self.set_time = set_time
        self.gps_fix_status = False   # typically 0,1 or 3
        self.latitude = ""
        self.longitude = ""
        self.quality_indicator = ""   # used for gps_fix too
        self.satellites = ""
        self.gpstime = ""             # from gga (fix) message
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
    def weekday(year, month, day):
        # Returns weekday for RTC set. Thanks to 2DOF @ Github
        t = [0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4]
        year -= month < 3
        return (year + int(year / 4) - int(year / 100) + int(year / 400) + t[month - 1] + day) % 7

    @staticmethod
    def checksum(nmeaword):
        # Calculates NMEA message checksum and compares to *xx checksum in the message
        linebegin = nmeaword.find(bytes(start_code, 'UTF-8'))
        cksumlenght = nmeaword.find(b'\r\n')
        cksumbegin = nmeaword.rfind(b'*')
        if linebegin == -1 or cksumbegin == -1 or cksumlenght == -1:
            return False
        # XORed checksum
        cksum = str(nmeaword[cksumbegin+1:cksumlenght].decode("utf-8"))   # cksum in nmeaword
        chksumdata = nmeaword[linebegin+1:cksumbegin].decode("utf-8")     # stripped nmeaword
        csum = 0
        for c in chksumdata:
            csum ^= ord(c)
        if hex(csum) == hex(int(cksum,16)):
            return True
        else:
            return False

    @staticmethod
    def convert_to_degree(rawdegrees):
        # Converts to degree. Thanks to microcontrollerlab article.
        rawasfloat = float(rawdegrees)
        firstdigits = int(rawasfloat / 100)
        nexttwodigits = rawasfloat - float(firstdigits * 100)
        converted = float(firstdigits + nexttwodigits / 60.0)
        converted = '{0:.6f}'.format(converted)
        return str(converted)


    async def reader(self):
        # Reads the UART port via StreamReader and check validity of the NMEA message.
        # Catch NMEA 0183 protocol message header, such as GPGGA, GPRMC etc. without GP (system code)
        # Keeps byte coding.
        port = asyncio.StreamReader(self.moduleUart)
        try:
            datain = await port.readline()
        except MemoryError:
            gc.collect()
            return False
        try:
            self.checksum(datain)
        except ValueError:
            return False
        except False:
            return False
        self.readdata = datain
        self.readtime = time.time()
        pos = datain.find(bytes(start_code + system_code,'UTF-8'))
        if pos == -1:
            return False
        else:
            self.foundcode = datain[pos + 3: pos + 6]  # returns 3 letter GP-xxx code
            decoded_data = str(self.readdata.decode('utf-8'))
            self.readdata = decoded_data.split(',')
            if self.debug_gen is True:
                print("Found code: %s and read data is: %s" % (self.foundcode, self.readdata))
            return True

    async def read_async_loop(self):
        # Forever running loop initiated from the main

        while True:
            if (time.time() - self.readtime) >= self.read_interval:
                await self.reader()
                if self.foundcode == b'GGA' and len(self.readdata) == 15:
                    self.latitude = self.convert_to_degree(self.readdata[2])
                    if self.readdata[3] == 'S':
                        self.latitude = "-" + self.latitude
                    self.longitude = self.convert_to_degree(self.readdata[4])
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
                if self.foundcode == b'VTG' and len(self.readdata) == 10:
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
                if self.foundcode == b'GLL' and len(self.readdata) == 7:
                    # 0 = Message ID $GPGLL, 1 = Latitude in dd mm,mmmm format (0-7 decimal places)
                    # 2 = Direction of latitude N: North S: South
                    # 3 = Longitude in ddd mm,mmmm format (0-7 decimal places)
                    # 4 = Direction of longitude E: East W: West
                    # 5 = UTC of position in hhmmss.ss format
                    # 6 = Status indicator: A: Data valid, V: Data not valid
                    if self.debug_gll is True:
                        print("--- GLL not implemented ---")
                if self.foundcode == b'GSV' and len(self.readdata) == 7:
                    # NMEA-0183 message:
                    # 1 = Total number of messages of this type in this cycle,2 = Message number,
                    # 3 = Total number of SVs in view
                    # 4 = SV PRN number, 5= Elevation in degrees, 90 maximum, 6 = Azimuth, dg from true north
                    # 7 = SNR, 00-99 dB,8-19 = Information about SVs'
                    if self.debug_gsv is True:
                        print("--- GSV not implemented ---")
                if self.foundcode == b'GSA' and len(self.readdata) == 7:
                    # 1= Mode:M=Manual, forced to operate in 2D or 3D, A=Automatic, 3D/2D
                    # 2= Mode: 1=Fix not available, 2=2Dm 3=3D
                    # 3-6 = IDs of SVs, PDOP,HDOP and VDOP
                    if self.debug_gsa is True:
                        print("--- GSA not implemented ---")
                if self.foundcode == b'RMC' and len(self.readdata) == 13:
                    gpstime_h = int(self.readdata[1][0:2])
                    gpstime_m = int(self.readdata[1][2:4])
                    gpstime_s = int(self.readdata[1][4:6])
                    if self.readdata[2] =='V':
                        self.data_valid = False
                    if self.readdata[2] == 'A':
                        self.data_valid = True
                    self.spd_o_g = self.readdata[7]
                    self.course_o_g = self.readdata[8]
                    self.ddmmyy = self.readdata[9]
                    if self.set_time is True and self.data_valid is True:
                        year = int('20'+ self.ddmmyy[4:6])
                        month = int(self.ddmmyy[2:4])
                        date = int(self.ddmmyy[0:2])
                        weekday = self.weekday(year, month, date)
                        # Set system time!
                        rtc_clock.datetime((year,month,date, weekday, gpstime_h, gpstime_m, gpstime_s,0))
                    if self.debug_rmc is True:
                        print("--- RMC debug ---")
                        print("GPSTime: %s" % self.gpstime)
                        print("System time set: ", time.localtime())
                        print("Data valid %s:" %self.data_valid)
                        print("Speed over ground: %s" %self.spd_o_g)
                        print("Course over ground: %s" %self.course_o_g)
                        print("--- End of RMC ---")
            await asyncio.sleep_ms(25)
