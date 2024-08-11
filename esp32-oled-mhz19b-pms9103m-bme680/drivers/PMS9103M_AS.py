# 11.08.2024 - Jari Hiltunen

from machine import UART
import gc
import struct
import utime
import uasyncio as asyncio


class PSensorPMS9103M:
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

    # Correctly calculate the checksum for the active mode command
    @staticmethod
    def calculate_checksum(command):
        checksum = sum(command) & 0xFFFF  # ensure it's a 16-bit sum
        return checksum

    def __init__(self, rxpin=32, txpin=33, uart=1):
        self.sensor = UART(uart)
        self.sensor.init(baudrate=9600, bits=8, parity=None, stop=1, rx=rxpin, tx=txpin)
        self.pms_dictionary = None
        self.last_read = 0
        self.startup_time = utime.time()
        self.read_interval = 10
        self.debug = False
        active_mode_command = bytearray([0x42, 0x4d, 0xe1, 0x01, 0x00, 0x00, 0x00, 0x00])
        checksum = self.calculate_checksum(active_mode_command)
        self.PMS_ACTIVE_MODE = active_mode_command + bytearray([checksum >> 8, checksum & 0xFF])

    async def writer(self, data):
        port = asyncio.StreamWriter(self.sensor, {})
        port.write(data)
        await port.drain()

    async def reader(self, chars):
        self.last_read = utime.time()
        port = asyncio.StreamReader(self.sensor)
        try:
            data = await port.readexactly(chars)
            if self.debug is True:
                print("PMS reader data %s" % data)
            if len(data) == int(chars):
                return data
            else:
                return False
        except MemoryError as err:
            if self.debug is True:
                print("PMS Error: %s" % err)
            gc.collect()
            return False

    @staticmethod
    def _assert_byte(byte, expected):
        if byte is None or len(byte) < 1 or ord(byte) != expected:
            return False
        return True

    async def read_async_loop(self):
        # Set active mode
        await self.writer(self.PMS_ACTIVE_MODE)

        while True:

            if (utime.time() - self.last_read) < self.read_interval:
                await asyncio.sleep(1)
            else:
                first_byte = await self.reader(1)
                if not self._assert_byte(first_byte, PSensorPMS9103M.START_BYTE_1):
                    continue
                second_byte = await self.reader(1)
                if not self._assert_byte(second_byte, PSensorPMS9103M.START_BYTE_2):
                    continue
                # we are reading 30 bytes left
                read_bytes = await self.reader(30)
                if len(read_bytes) < 30:
                    continue
                data = struct.unpack('!HHHHHHHHHHHHHBBH', read_bytes)
                checksum = PSensorPMS9103M.START_BYTE_1 + PSensorPMS9103M.START_BYTE_2
                checksum += sum(read_bytes[:28])
                if checksum != data[PSensorPMS9103M.PMS_CHECKSUM]:
                    continue
                self.pms_dictionary = {
                    'FRAME_LENGTH': data[PSensorPMS9103M.PMS_FRAME_LENGTH],
                    'PM1_0': data[PSensorPMS9103M.PMS_PM1_0],
                    'PM2_5': data[PSensorPMS9103M.PMS_PM2_5],
                    'PM10_0': data[PSensorPMS9103M.PMS_PM10_0],
                    'PM1_0_ATM': data[PSensorPMS9103M.PMS_PM1_0_ATM],
                    'PM2_5_ATM': data[PSensorPMS9103M.PMS_PM2_5_ATM],
                    'PM10_0_ATM': data[PSensorPMS9103M.PMS_PM10_0_ATM],
                    'PCNT_0_3': data[PSensorPMS9103M.PMS_PCNT_0_3],
                    'PCNT_0_5': data[PSensorPMS9103M.PMS_PCNT_0_5],
                    'PCNT_1_0': data[PSensorPMS9103M.PMS_PCNT_1_0],
                    'PCNT_2_5': data[PSensorPMS9103M.PMS_PCNT_2_5],
                    'PCNT_5_0': data[PSensorPMS9103M.PMS_PCNT_5_0],
                    'PCNT_10_0': data[PSensorPMS9103M.PMS_PCNT_10_0],
                    'VERSION': data[PSensorPMS9103M.PMS_VERSION],
                    'ERROR': data[PSensorPMS9103M.PMS_ERROR],
                    'CHECKSUM': data[PSensorPMS9103M.PMS_CHECKSUM], }
