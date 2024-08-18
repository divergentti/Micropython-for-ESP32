"""
  19.01.2020: Jari Hiltunen

  Original https://github.com/pkucmus/micropython-pms7003/blob/master/pms7003.py
  Modified for asyncronous StreamReader  16.01.2020 by Divergentti / Jari Hiltunen

  Add loop into your code loop.create_task(objectname.read_async_loop())

"""

from machine import UART, Pin
import gc
import struct
import utime
import uasyncio as asyncio


class PMS:

    START_BYTE_1 = 0x42
    START_BYTE_2 = 0x4d
    PMS_FRAME_LENGTH = 0
    PMS_PM1_0 = 1
    PMS_PM2_5 = 2
    PMS_PM10_0 = 3
    PMS_PM1_0_ATM = 4
    PMS_PM2_5_ATM = 5
    PMS_PM10_0_ATM = 6
    PMS_PCNT_0_3 = 7
    PMS_PCNT_0_5 = 8
    PMS_PCNT_1_0 = 9
    PMS_PCNT_2_5 = 10
    PMS_PCNT_5_0 = 11
    PMS_PCNT_10_0 = 12
    PMS_VERSION = 13
    PMS_ERROR = 14
    PMS_CHECKSUM = 15

    #  Default UART1, rx=32, tx=33. Don't use UART0 if you want to use REPL!
    def __init__(self, rxpin=16, txpin=17, uart=2):
        self.sensor = UART(uart, baudrate=9600, bits=8, parity=None, stop=1, rx=Pin(rxpin), tx=Pin(txpin))
        self.pms_dictionary = None
        self.startup_time = utime.time()
        self.read_time = 0
        self.read_interval = 30
        self.debug = False

    async def reader(self, chars):
        port = asyncio.StreamReader(self.sensor)
        try:
            data = await port.readexactly(chars)
            if self.debug:
                print("PMS data in %s" % data)
            if len(data) == int(chars):
                return data
            else:
                return False
        except MemoryError:
            gc.collect()
            return False

    @staticmethod
    def _assert_byte(byte, expected):
        if byte is None or len(byte) < 1 or ord(byte) != expected:
            return False
        return True

    async def read_async_loop(self):

        while True:

            first_byte = await self.reader(1)
            if not self._assert_byte(first_byte, PMS.START_BYTE_1):
                continue

            second_byte = await self.reader(1)
            if not self._assert_byte(second_byte, PMS.START_BYTE_2):
                continue

            # we are reading 30 bytes left
            read_bytes = await self.reader(30)
            if len(read_bytes) < 30:
                continue

            data = struct.unpack('!HHHHHHHHHHHHHBBH', read_bytes)

            checksum = PMS.START_BYTE_1 + PMS.START_BYTE_2
            checksum += sum(read_bytes[:28])

            if checksum != data[PMS.PMS_CHECKSUM]:
                continue

            self.pms_dictionary = {
                'FRAME_LENGTH': data[PMS.PMS_FRAME_LENGTH],
                'PM1_0': data[PMS.PMS_PM1_0],
                'PM2_5': data[PMS.PMS_PM2_5],
                'PM10_0': data[PMS.PMS_PM10_0],
                'PM1_0_ATM': data[PMS.PMS_PM1_0_ATM],
                'PM2_5_ATM': data[PMS.PMS_PM2_5_ATM],
                'PM10_0_ATM': data[PMS.PMS_PM10_0_ATM],
                'PCNT_0_3': data[PMS.PMS_PCNT_0_3],
                'PCNT_0_5': data[PMS.PMS_PCNT_0_5],
                'PCNT_1_0': data[PMS.PMS_PCNT_1_0],
                'PCNT_2_5': data[PMS.PMS_PCNT_2_5],
                'PCNT_5_0': data[PMS.PMS_PCNT_5_0],
                'PCNT_10_0': data[PMS.PMS_PCNT_10_0],
                'VERSION': data[PMS.PMS_VERSION],
                'ERROR': data[PMS.PMS_ERROR],
                'CHECKSUM': data[PMS.PMS_CHECKSUM], }
            self.read_time = utime.time()
            if self.debug:
                print("PMS Read at %s" % self.read_time)
            await asyncio.sleep(self.read_interval)
