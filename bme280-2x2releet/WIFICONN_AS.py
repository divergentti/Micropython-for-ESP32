# This class is for asynchronous WiFi connection.
#
#   7.2.2024: Jari Hiltunen / Divergentti
#
#   in your main.py:
#   import WIFICONN_AS as WNET
#   net = WNET.ConnectWiFi(ssid1, pw for ssid1, ssid2, pw for 2, ntpserver  name, dhcpname, startwebrepl, wbpassword)
#   ...
#   your asynchronous code ...
#   async def main():
#   loop = asyncio.get_event_loop()
#   loop.create_task(net.net_upd_loop())
#   loop.run_forever()


import gc
import uasyncio as asyncio
import network
import ntptime
gc.collect()


class ConnectWiFi(object):
    """ Class initialize WI-FI and tries to connect two predefined APs """

    def __init__(self, ssid1, password1, ssid2=None, password2=None, ntpserver='fi.pool.ntp.org', dhcpname=None,
                 startwebrepl=False, webreplpwd=None):
        self.sid1 = ssid1
        self.pw1 = password1
        self.sid2 = ssid2
        self.pw2 = password2
        self.ntps = ntpserver
        self.dhcpn = dhcpname
        if startwebrepl == 1:
            self.s_wbr = True
        else:
            self.s_wbr = False
        self.wbrpl_pwd = webreplpwd
        self.net_ok = False
        self.pwd = None
        self.u_pwd = None
        self.use_ssid = None
        self.ip_a = None
        self.strength = None
        self.wbrpl_sted = False
        self.scan_ok = False
        self.time_set = False
        self.last_err = None

    async def net_upd_loop(self):
        if self.dhcpn is not None:
            network.WLAN(network.STA_IF).config(dhcp_hostname=self.dhcpn)
        if self.ntps is not None:
            ntptime.host = self.ntps

        while True:
            # Scan available APs and check if they are in list
            if (self.net_ok is False) and (self.scan_ok is False):
                try:
                    await self.s_nets()
                except False:
                    print("Scan error: %s" % self.last_err)

            if (self.scan_ok is True) and (self.net_ok is False):
                # Try to connect
                try:
                    network.WLAN(network.STA_IF).connect(self.use_ssid, self.u_pwd)
                    await asyncio.sleep(10)
                except network.WLAN(network.STA_IF).ifconfig()[0] == '0.0.0.0':
                    self.net_ok = False
                    self.last_err = "IP 0.0.0.0"
                    print("Connect error %s" % self.last_err)
                except OSError as e:
                    self.net_ok = False
                    self.last_err = e
                    print("Connect error %s" % self.last_err)
                else:
                    self.use_ssid = network.WLAN(network.STA_IF).config('essid')
                    self.ip_a = network.WLAN(network.STA_IF).ifconfig()[0]
                    self.strength = network.WLAN(network.STA_IF).status('rssi')
                    self.net_ok = True

            if (self.net_ok is True) and (self.time_set is False):
                try:
                    ntptime.settime()
                except OSError as e:
                    self.last_err = e
                    self.time_set = False
                else:
                    self.time_set = True

            if ((self.net_ok is True) and (self.s_wbr is True) and
                    (self.wbrpl_pwd is not None) and (self.wbrpl_sted is False)):
                import webrepl
                # Note! Execute in REPL command import webrepl_setup  !! Check boot.py after setup!
                try:
                    webrepl.start(password=self.wbrpl_pwd)
                    webrepl.start()
                except NameError as e:
                    self.wbrpl_sted = False
                    self.last_err = e
                except OSError as e:
                    self.wbrpl_sted = False
                    self.last_err = e
                else:
                    self.wbrpl_sted = True

            await asyncio.sleep(1)

    async def s_nets(self):
        ssid_list = []
        network.WLAN(network.STA_IF).active(True)
        try:
            ssid_list = network.WLAN(network.STA_IF).scan()
            await asyncio.sleep(5)
        except ssid_list == []:
            self.last_err = "Empty SSID list!"
            self.scan_ok = False
        except OSError as e:
            self.last_err = e
            self.scan_ok = False
        else:
            if (item for item in ssid_list if item[0].decode() == self.sid1):
                self.use_ssid = self.sid1
                self.u_pwd = self.pw1
                self.scan_ok = True
            elif (item for item in ssid_list if item[0].decode() == self.sid2):
                self.use_ssid = self.sid2
                self.u_pwd = self.pw2
                self.scan_ok = True
            else:
                self.last_err = "AP1 or AP2 not found in range!"
                self.scan_ok = False
