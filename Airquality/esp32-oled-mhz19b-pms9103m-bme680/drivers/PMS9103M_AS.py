"""
  20.08.2024: Jari Hiltunen

  Active mode UART driver for PMS9103M (and 7000 etc)

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
    PMS_ACTIVE_MODE = bytearray([0x42, 0x4d, 0xe1, 0x00, 0x01, 0x01, 0x71])
    PMS_WAKEUP = bytearray([0x42, 0x4d, 0xe4, 0x00, 0x01, 0x01, 0x74])


    #  Default UART1, rx=32, tx=33. Don't use UART0 if you want to use REPL!
    def __init__(self, rxpin=16, txpin=17, uart=2):
        self.sensor = UART(uart, baudrate=9600, bits=8, parity=None, stop=1, rx=Pin(rxpin), tx=Pin(txpin))
        self.pms_dictionary = None
        self.debug = False
        self.startup_time = utime.time()
        self.read_time = 0
        self.read_interval = 10

    async def wake_and_set_active(self):
        # This is future reservation - not used
        asyncio.run(self.writer(self.PMS_WAKEUP))
        if (self.reader(1) != 7) and (self.debug is True):
            print("PMS Wakeup failed!")
        asyncio.run(self.writer(self.PMS_ACTIVE_MODE))
        if (self.reader(1) != 7) and (self.debug is True):
            print("PMS Set Active failed!")

    async def writer(self, data):
        port = asyncio.StreamWriter(self.sensor, {})
        port.write(data)
        await port.drain()
        await asyncio.sleep(2)

    async def reader(self, chars, timeout=5):
        port = asyncio.StreamReader(self.sensor)
        start_time = utime.time()  # Get the current time
        data = bytearray()

        while len(data) < chars:
            # Check if timeout has passed
            if utime.time() - start_time >= timeout:
                if self.debug:
                    print(f"Timeout occurred after {timeout} seconds")
                return False  # Return False if timeout occurs

            try:
                chunk = await port.read(1)  # Read byte by byte
                if chunk:
                    data += chunk
            except MemoryError:
                gc.collect()
                return False

        if len(data) == chars:
            if self.debug:
                print(f"Data received: {data}")
            return data
        return False  # In case of incomplete read

    @staticmethod
    def _assert_byte(byte, expected):
        if byte is None or len(byte) < 1 or byte[0] != expected:  # Access the first element of the bytearray
            return False
        return True

    async def read_async_loop(self):
        while True:
            first_byte = await self.reader(1)
            if not self._assert_byte(first_byte, PMS.START_BYTE_1):
                if self.debug:
                    print(f"Invalid first byte: {first_byte}")
                continue

            second_byte = await self.reader(1)
            if not self._assert_byte(second_byte, PMS.START_BYTE_2):
                if self.debug:
                    print(f"Invalid second byte: {second_byte}")
                continue

            # Reading 30 more bytes
            read_bytes = await self.reader(30)
            if len(read_bytes) < 30:
                if self.debug:
                    print(f"Incomplete read: {read_bytes}")
                continue

            if self.debug:
                print(f"Raw data received: {read_bytes}")

            # Unpack the data
            data = struct.unpack('!HHHHHHHHHHHHHBBH', read_bytes)

            # Calculate checksum
            checksum = PMS.START_BYTE_1 + PMS.START_BYTE_2
            checksum += sum(read_bytes[:28])

            if checksum != data[PMS.PMS_CHECKSUM]:
                if self.debug:
                    print(f"Checksum error: {checksum} != {data[PMS.PMS_CHECKSUM]}")
                continue

            # Populate the dictionary
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
                'CHECKSUM': data[PMS.PMS_CHECKSUM],
            }
            self.read_time = utime.time()
            if self.debug:
                print(f"PMS Read at {self.read_time}, data: {self.pms_dictionary}")
                if data[PMS.PMS_ERROR] != 0:
                    print(f"PMS reports error {data[PMS.PMS_ERROR]}")
            await asyncio.sleep(self.read_interval)

