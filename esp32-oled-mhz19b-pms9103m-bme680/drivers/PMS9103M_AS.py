# 18.08.2024 - Jari Hiltunen
# In the main, loop.create_task(objectname.read_async_loop())

from machine import UART, Pin
import utime
import uasyncio as asyncio


class PMS:
    # Write commands:
    # Start Byte 1 Start Byte 2 Command Data 1 Data 2     Verify Byte 1 Verify Byte 2
    # 0x42         0x4d         CMD     DATAH  DATAL      LRCH          LRCL
    # 0x42         0x4d         0xe2    0x00   0x00                              = Read in passive mode
    # 0x42         0x4d         0xe1    0x00   0x00/0x01                         = 0x00 = passive, 0x01 = active
    # 0x42         0x4d         0xe4    0x00   0x00/0x01                         = 0x00 = sleep, 0x01 = wakeup
    # Commands without CRC bytes
    CMD_WAKEUP = bytearray([0x42, 0x4d, 0xe4, 0x00, 0x01])
    CMD_SLEEP = bytearray([0x42, 0x4d, 0xe4, 0x00, 0x00])
    CMD_ACTIVE_MODE = bytearray([0x42, 0x4d, 0xe1, 0x00, 0x01])
    CMD_PASSIVE_MODE = bytearray([0x42, 0x4d, 0xe1, 0x00, 0x00])
    # Read passive command 0xe2 returns 32 bytes with PCNT and PM-values
    CMD_READ_PASSIVE = bytearray([0x42, 0x4d, 0xe2, 0x00, 0x00])

    START_BYTE_1 = 0x42
    START_BYTE_2 = 0x4d
    PM1_OFFSET = 6
    PM2P5_OFFSET = 8
    PM10_OFFSET = 10
    PM1_ATM_OFFSET = 12
    PM2P5_ATM_OFFSET = 14
    PM10_ATM_OFFSET = 16
    PCNT0_3_OFFSET = 18
    PCNT0_5_OFFSET = 20
    PCNT1_0_OFFSET = 22
    PCNT2_5_OFFSET = 24
    PCNT5_0_OFFSET = 25
    PCNT10_OFFSET = 26
    VERSION_OFFSET = 28
    ERROR_OFFSET = 30
    MAX_DATA_LENGTH = 28
    READ_INTERVAL = 10

    @staticmethod
    def calculate_checksum(command):
        checksum = sum(command) & 0xFFFF
        lrch = (checksum >> 8) & 0xFF
        lrcl = checksum & 0xFF
        return lrch, lrcl

    def verify_checksum(self, frame):
        checksum = self.calculate_checksum(frame)
        return (frame[-2] << 8 | frame[-1]) == checksum

    async def writer(self, data):
        port = asyncio.StreamWriter(self.sensor, {})
        port.write(data)
        await port.drain()
        await asyncio.sleep(0.1)

    def __init__(self, rxpin=32, txpin=33, uart=1):
        self.sensor = UART(uart)
        self.sensor.init(baudrate=9600, bits=8, parity=None, stop=1, rx=Pin(rxpin), tx=Pin(txpin))
        self.buffer = bytearray(PMS.MAX_DATA_LENGTH)
        self.pms_dictionary = None
        self.last_read = 0
        self.startup_time = utime.time()
        self.read_interval = 30
        self.debug = False
        self.wake_up()
        self.enter_passive_mode()

    async def read_frame(self):
        while self.sensor.any() < self.MAX_DATA_LENGTH:
            await asyncio.sleep(0.1)
        asyncio.StreamReader(self.sensor).readinto(self.buffer)
        return self.buffer

    async def read_pm_values(self):
        checksum_high, checksum_low = self.calculate_checksum(self.CMD_READ_PASSIVE)
        await self.writer(self.CMD_READ_PASSIVE + bytearray([checksum_high, checksum_low]))
        frame = await self.read_frame()

        if self.verify_checksum(frame):
            pm1 = frame[self.PM1_OFFSET] << 8 | frame[self.PM1_OFFSET + 1]
            pm1_atm = frame[self.PM1_ATM_OFFSET] << 8 | frame[self.PM1_ATM_OFFSET + 1]
            pm2_5 = frame[self.PM2P5_OFFSET] << 8 | frame[self.PM2P5_OFFSET + 1]
            pm2_5_atm = frame[self.PM2P5_ATM_OFFSET] << 8 | frame[self.PM2P5_ATM_OFFSET + 1]
            pm10 = frame[self.PM10_OFFSET] << 8 | frame[self.PM10_OFFSET + 1]
            pm10_atm = frame[self.PM10_ATM_OFFSET] << 8 | frame[self.PM10_ATM_OFFSET + 1]
            pcnt0_3 = frame[self.PCNT0_3_OFFSET] << 8 | frame[self.PCNT0_3_OFFSET + 1]
            pcnt0_5 = frame[self.PCNT0_5_OFFSET] << 8 | frame[self.PCNT0_5_OFFSET + 1]
            pcnt1_0 = frame[self.PCNT1_0_OFFSET] << 8 | frame[self.PCNT1_0_OFFSET + 1]
            pcnt2_5 = frame[self.PCNT2_5_OFFSET] << 8 | frame[self.PCNT2_5_OFFSET + 1]
            pcnt5_0 = frame[self.PCNT5_0_OFFSET] << 8 | frame[self.PCNT5_0_OFFSET + 1]
            pcnt10 = frame[self.PCNT10_OFFSET] << 8 | frame[self.PCNT10_OFFSET + 1]
            version = frame[self.VERSION_OFFSET] << 8 | frame[self.VERSION_OFFSET + 1]
            error = frame[self.ERROR_OFFSET] << 8 | frame[self.ERROR_OFFSET + 1]
            self.last_read = utime.time()
            self.pms_dictionary = {
                'PM1_0': pm1,
                'PM2_5': pm2_5,
                'PM10_0': pm10,
                'PM1_0_ATM': pm1_atm,
                'PM2_5_ATM': pm2_5_atm,
                'PM10_0_ATM': pm10_atm,
                'PCNT_0_3': pcnt0_3,
                'PCNT_0_5': pcnt0_5,
                'PCNT_1_0': pcnt1_0,
                'PCNT_2_5': pcnt2_5,
                'PCNT_5_0': pcnt5_0,
                'PCNT_10_0': pcnt10,
                'VERSION': version,
                'ERROR': error
            }
            self.last_read = utime.time()
            return True
        else:
            if self.debug is True:
                print("Error: Incomplete data frame.")
            return False

    async def wake_up(self):
        checksum_high, checksum_low = self.calculate_checksum(self.CMD_WAKEUP)
        await self.writer(self.CMD_WAKEUP + bytearray([checksum_high, checksum_low]))

    async def sleep(self):
        checksum_high, checksum_low = self.calculate_checksum(self.CMD_SLEEP)
        await self.writer(self.CMD_SLEEP + bytearray([checksum_high, checksum_low]))

    async def enter_passive_mode(self):
        checksum_high, checksum_low = self.calculate_checksum(self.CMD_PASSIVE_MODE)
        await self.writer(self.CMD_PASSIVE_MODE + bytearray([checksum_high, checksum_low]))

    async def enter_active_mode(self):
        checksum_high, checksum_low = self.calculate_checksum(self.CMD_ACTIVE_MODE)
        await self.writer(self.CMD_ACTIVE_MODE + bytearray([checksum_high, checksum_low]))

    async def read_async_loop(self):
        while True:
            status = await self.read_pm_values()  # Await the coroutine
            if self.debug:
                print("PMS read status: %s" % status)
            await asyncio.sleep(self.READ_INTERVAL)
