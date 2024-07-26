# This class is for asynchronous WiFi connection. 6.6.2023: Jari Hiltunen / Divergentti
# Tries to connect to 2 different APs
# in main.py:
# net = WIFINET.ConnectWiFi(ssid1, pw for ssid1, ssid2, pw for 2, ntpserver  name, dhcpname, startwebrepl, wbpassword)
# ... your asynchronous code ...
# async def main():
#   loop = asyncio.get_event_loop()
#   loop.create_task(net.net_upd_loop())
#   loop.run_forever()

import gc
import uasyncio as asyncio
import network
import ntptime
import webrepl
from utime import time
gc.collect()


class ConnectWiFi(object):

    def __init__(self, ssid1, password1, ssid2=None, password2=None, ntpserver='fi.pool.ntp.org', dhcpname=None,
                 startwebrepl=False, webreplpwd=None):
        self.ssid1 = ssid1
        self.pw1 = password1
        self.ssid2 = ssid2
        self.pw2 = password2
        self.ntps = ntpserver
        self.dhcpn = dhcpname
        self.starwbr = startwebrepl
        self.webrplpwd = webreplpwd
        self.net_ok = False
        self.password = None
        self.u_pwd = None
        self.use_ssid = None
        self.ip_a = None
        self.strength = None
        self.webrepl_started = False
        self.startup_time = None

    async def net_upd_loop(self):
        while True:
            if not self.net_ok:
                await self.connect_to_network()
            await asyncio.sleep(1)

    async def start_webrepl(self):
        if (self.webrepl_started is False) and (self.starwbr is True) and (self.webrplpwd is not None):
            try:
                webrepl.start(password=self.webrplpwd)
                webrepl.start()
                self.webrepl_started = True
                return True
            except OSError as e:
                self.webrepl_started = False
                return False

    async def set_time(self):
        ntptime.host = self.ntps
        try:
            ntptime.settime()
            return True
        except OSError as e:
            return False

    async def s_nets(self):
        ssid_list = []
        network.WLAN(network.STA_IF).active(True)
        try:
            ssid_list = network.WLAN(network.STA_IF).scan()
            await asyncio.sleep(5)
        except ssid_list == []:
            return False
        except OSError as e:
            return False
        if (item for item in ssid_list if item[0].decode() == self.ssid1):
            self.use_ssid = self.ssid1
            self.u_pwd = self.pw1
            return True
        elif (item for item in ssid_list if item[0].decode() == self.ssid2):
            self.use_ssid = self.ssid2
            self.u_pwd = self.pw2
            return True
        else:
            print("s_nets: either AP1 or AP2 not found in range!")
            return False


    async def connect_to_network(self):
        try:
            await self.s_nets()
        except False:
            return False
        if self.dhcpn is not None and (len(self.dhcpn) < 15):
            # Since version 1.2 <15 characters
            network.WLAN(network.STA_IF).config(dhcp_hostname=self.dhcpn)
        try:
            network.WLAN(network.STA_IF).connect(self.use_ssid, self.u_pwd)
            await asyncio.sleep(10)
        except network.WLAN(network.STA_IF).ifconfig()[0] == '0.0.0.0':
            self.net_ok = False
            return False
        except OSError as e:
            return False
        finally:
            if network.WLAN(network.STA_IF).ifconfig()[0] != '0.0.0.0':
                self.use_ssid = network.WLAN(network.STA_IF).config('essid')
                self.ip_a = network.WLAN(network.STA_IF).ifconfig()[0]
                self.strength = network.WLAN(network.STA_IF).status('rssi')
                await self.set_time()
                if (self.starwbr is True) and (self.webrepl_started is False):
                    await self.start_webrepl()
                self.startup_time = time()
                self.net_ok = True
                return True
            else:
                self.net_ok = False
                return False
