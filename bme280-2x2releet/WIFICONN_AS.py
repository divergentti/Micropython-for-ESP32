""" This class is for asynchronous WiFi connection. 6.6.2023: Jari Hiltunen / Divergentti
in your main.py:
    net = WIFINET.ConnectWiFi(ssid1, pw for ssid1, ssid2, pw for 2, ntpserver  name, dhcpname, startwebrepl, wbpassword)
    ...
    your asynchronous code ...
    async def main():
    loop = asyncio.get_event_loop()
    loop.create_task(net.net_upd_loop())
    loop.run_forever()
"""

import gc
import uasyncio as asyncio
import network
import ntptime
import webrepl   # Note! Execute in REPL command import webrepl_setup  !!
from utime import time
gc.collect()


class ConnectWiFi(object):
    """ Class initialize WIFI and tries to connect two predefined APs """

    def __init__(self, ssid1, password1, ssid2=None, password2=None, ntpserver='fi.pool.ntp.org', dhcpname=None,
                 startwebrepl=False, webreplpwd=None):
        self.sid1 = ssid1
        self.pw1 = password1
        self.sid2 = ssid2
        self.pw2 = password2
        self.ntps = ntpserver
        self.dhcpn = dhcpname
        self.starwbr = startwebrepl
        self.webrplpwd = webreplpwd
        self.net_ok = False
        self.pwd = None
        self.u_pwd = None
        self.use_ssid = None
        self.ip_a = None
        self.strength = None
        self.webrpl_sted = False
        self.start_time = None
        self.last_err = None

    async def net_upd_loop(self):
        while True:
            if not self.net_ok:
                await self.con_to_net()
            await asyncio.sleep(1)

    async def s_webrpl(self):
        if (self.webrpl_sted is False) and (self.starwbr is True) and (self.webrplpwd is not None):
            try:
                webrepl.start(password=self.webrplpwd)
                webrepl.start()
                self.webrpl_sted = True
            except OSError as e:
                self.webrpl_sted = False
                self.last_err = e
                return False
            else:
                return True

    async def set_time(self):
        ntptime.host = self.ntps
        try:
            ntptime.settime()
        except OSError as e:
            self.last_err = e
            return False
        else:
            return True

    async def s_nets(self):
        ssid_list = []
        network.WLAN(network.STA_IF).active(True)
        try:
            ssid_list = network.WLAN(network.STA_IF).scan()
            await asyncio.sleep(5)
        except ssid_list == []:
            self.last_err = "Empty SSID list"
            return False
        except OSError as e:
            self.last_err = e
            return False
        if (item for item in ssid_list if item[0].decode() == self.sid1):
            self.use_ssid = self.sid1
            self.u_pwd = self.pw1
            return True
        elif (item for item in ssid_list if item[0].decode() == self.sid2):
            self.use_ssid = self.sid2
            self.u_pwd = self.pw2
            return True
        else:
            self.last_err = "AP1 or AP2 not found in range!"
            return False


    async def con_to_net(self):
        try:
            await self.s_nets()
        except False:
            return False
        if self.dhcpn is not None:
            network.WLAN(network.STA_IF).config(dhcp_hostname=self.dhcpn)
        try:
            network.WLAN(network.STA_IF).connect(self.use_ssid, self.u_pwd)
            await asyncio.sleep(10)
        except network.WLAN(network.STA_IF).ifconfig()[0] == '0.0.0.0':
            self.net_ok = False
            self.last_err = "IP 0.0.0.0"
            return False
        except OSError as e:
            self.last_err = e
            return False
        finally:
            if network.WLAN(network.STA_IF).ifconfig()[0] != '0.0.0.0':
                self.use_ssid = network.WLAN(network.STA_IF).config('essid')
                self.ip_a = network.WLAN(network.STA_IF).ifconfig()[0]
                self.strength = network.WLAN(network.STA_IF).status('rssi')
                await self.set_time()
                if (self.starwbr is True) and (self.webrpl_sted is False):
                    await self.s_webrpl()
                self.start_time = time()
                self.net_ok = True
                return True
            else:
                self.net_ok = False
                self.last_err = "Last resort failed!"
                return False
