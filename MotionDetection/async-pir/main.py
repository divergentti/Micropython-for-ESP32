""" ESP32-Wroom-NodeMCU ja vastaaville (micropython)

    9.9.2020: Jari Hiltunen

    PIR HC-SR501-sensorille:
    Luetaan liiketunnistimelta tulevaa statustietoa, joko pinni päällä tai pois.
    Mikäli havaitaan liikettä, havaitaan keskeytys ja tämä tieto välitetään mqtt-brokerille.

    Sensori näkee 110 astetta, 7 metriin, kuluttaa 65mA virtaa ja toimii 4.5V - 20V jännitteellä.

    Keskimmäinen potentiometri säätää herkkyyttä, laitimmainen aikaa (0-300s) miten pitkään datapinnissä pysyy
    tila high päällä liikkeen havaitsemisen jälkeen. Blokkausaika on 2.5s eli sitä tiheämmin ei havaita muutosta.

    Jumpperi: alareunassa single triggeri, eli liikkeestä lähetetään vain yksi high-tila (3,3V). Eli
    jos ihminen liikkuu tilassa, high pysyy ylhäällä potentiometrillä säädetyn ajan verran ja palautuu
    nollaan. Yläreunassa repeat triggeri, eli lähetetään high-tilaa (3,3V) niin pitkään kun joku on tilassa.

    Käytä tämän scriptin kanssa repeat-tilaa ja säädä aika minimiin (laitimmainen potentionmetri äärivasen)!

    Kytkentä: keskimmäinen on datapinni (high/low), jumpperin puolella maa (gnd) ja +5V toisella puolella.
    Ota jännite ESP32:n 5V lähdöstä (VIN, alin vasemmalla päältä katsottuna antaa  4.75V).

    MQTT-brokerissa voi olla esimerkiksi ledinauhoja ohjaavat laitteet tai muut toimet, joita
    liiketunnistuksesta tulee aktivoida. Voit liittää tähän scriptiin myös releiden ohjauksen,
    jos ESP32 ohjaa samalla myös releitä.

    MQTT hyödyntää valmista kirjastoa umqttsimple.py joka on ladattavissa:
    https://github.com/micropython/micropython-lib/tree/master/umqtt.simple

    22.9.2020: Paranneltu WiFi-objektin hallintaa ja mqtt muutettu retain-tyyppiseksi.
    24.9.2020: Lisätty virheiden kirjaus tiedostoon ja lähetys mqtt-kanavaan. Poistettu ledivilkutus.
               Virheiden kirjauksessa erottimena toimii ";" eli puolipilkulla erotetut arvot.
    11.10.2020: Lisätty mqtt-pollaus siten, että jos mqtt-viestejä ei kuulu puoleen tuntiin, laite bootataan.
    2.11.2020:  Muutettu asynkroniseksi ja mahdollisuus laittaa viive tunnistukselle, oletuksena 2s.
"""
import time
import utime
import machine  # tuodaan koko kirjasto
from machine import Pin
from umqttsimple import MQTTClient
import gc
import os
import uasyncio as asyncio  # asynkroninen IO
# tuodaan parametrit tiedostosta parametrit.py
from parametrit import CLIENT_ID, MQTT_SERVERI, MQTT_PORTTI, MQTT_KAYTTAJA, \
    MQTT_SALASANA, PIR_PINNI, AIHE_LIIKETUNNISTIN, AIHE_VIRHEET
# tuodaan bootis wifi-ap:n objekti
from boot import wificlient_if


client = MQTTClient(CLIENT_ID, MQTT_SERVERI, MQTT_PORTTI, MQTT_KAYTTAJA, MQTT_SALASANA)

# MQTT-uptimelaskuri
mqtt_viimeksi_nahty = utime.ticks_ms()


def raportoi_virhe(virhe):
    # IN: str virhe = virheen tekstiosa
    try:
        tiedosto = open('virheet.txt', "r")
        # mikali tiedosto on olemassa, jatketaan
    except OSError:  # avaus ei onnistu, luodaan uusi
        tiedosto = open('virheet.txt', 'w')
        # virheviestin rakenne: pvm + aika;uptime;laitenimi;ip;virhe;vapaa muisti
    virheviesti = str(ratkaise_aika()) + ";" + str(utime.ticks_ms()) + ";" \
        + str(CLIENT_ID) + ";" + str(wificlient_if.ifconfig()) + ";" + str(virhe) +\
        ";" + str(gc.mem_free())
    tiedosto.write(virheviesti)
    tiedosto.close()


def ratkaise_aika():
    (vuosi, kuukausi, kkpaiva, tunti, minuutti, sekunti, viikonpva, vuosipaiva) = utime.localtime()
    aika = "%s.%s.%s klo %s:%s:%s" % (kkpaiva, kuukausi, vuosi, "{:02d}".format(tunti),
                                      "{:02d}".format(minuutti), "{:02d}".format(sekunti))
    return aika


def mqtt_palvelin_yhdista():
    aika = ratkaise_aika()
    if wificlient_if.isconnected() is True:
        try:
            client.connect()
            print("Yhdistetty %s palvelimeen %s" % (client.client_id, client.server))
            return True
        except OSError as e:
            print("% s:  Ei voida yhdistaa mqtt-palvelimeen! %s " % (aika, e))
            raportoi_virhe(e)
            restart_and_reconnect()
    elif wificlient_if.isconnected() is False:
        print("%s: Yhteys on poikki! Signaalitaso %s " % (aika, wificlient_if.status('rssi')))
        raportoi_virhe("Yhteys poikki rssi: %s" % wificlient_if.status('rssi'))
        restart_and_reconnect()


def restart_and_reconnect():
    aika = ratkaise_aika()
    print('%s: Ongelmia. Boottaillaan 1s kuluttua.' % aika)
    time.sleep(1)
    machine.reset()
    # resetoidaan


def tarkista_uptime(aihe, viesti):
    global mqtt_viimeksi_nahty
    # print("Aihe %s vastaanotettu, nollataan laskuri." % aihe)
    mqtt_viimeksi_nahty = utime.ticks_ms()


def tarkista_virhetiedosto():
    try:
        tiedosto = open('virheet.txt', "r")
        # mikali tiedosto on olemassa, jatketaan, silla virheita on ilmoitettu
    except OSError:  # avaus ei onnistu, eli tiedostoa ei ole, jatketaan koska ei virheita
        return
        #  Luetaan tiedoston rivit ja ilmoitetaan mqtt:lla
    rivit = tiedosto.readline()
    while rivit:
        try:
            client.publish(AIHE_VIRHEET, str(rivit), retain=False)
            rivit = tiedosto.readline()
        except OSError:
            #  Ei onnistu, joten bootataan
            restart_and_reconnect()
    #  Tiedosto luettu ja mqtt:lla ilmoitettu, suljetaan ja poistetaan se
    tiedosto.close()
    os.remove('virheet.txt')


class LiikeTunnistin:
    global mqtt_viimeksi_nahty, client

    def __init__(self, pinni, viive):
        self.pinni = Pin(pinni, Pin.IN)
        self.viive = viive
        self.liiketta = False  # Onko liikettä havaittu?
        self.on_aika = utime.time()
        self.off_aika = utime.time()
        self.ilmoitettu_aika = utime.time()
        self.ilmoitettu = False
        self.tila = 0
        self.edellinen_tila = 0

    async def laheta_status(self):
        if self.ilmoitettu is False and ((utime.time()-self.ilmoitettu_aika) > self.viive):
            try:
                client.publish(AIHE_LIIKETUNNISTIN, str(self.tila), qos=1, retain=True)
                self.ilmoitettu = True
                self.ilmoitettu_aika = utime.time()
                print("Ilmoitettu %s" % self.tila)
            except OSError as e:
                restart_and_reconnect()

    async def liike_looppi(self):
        self.tila = self.pinni.value()
        if self.tila == 1 and self.edellinen_tila == 0 and (utime.time() - self.on_aika) > self.viive:
            self.ilmoitettu = False
            self.on_aika = utime.time()
            self.liiketta = True
            self.edellinen_tila = 1
        if self.tila == 0 and self.edellinen_tila == 1 and (utime.time() - self.off_aika) > self.viive:
            self.ilmoitettu = False
            self.off_aika = utime.time()
            self.liiketta = False
            self.edellinen_tila = 0

    async def tarkista_viesti(self):
        client.check_msg()

    async def uptime_looppi(self):
        if (utime.ticks_diff(utime.ticks_ms(), mqtt_viimeksi_nahty)) > (60 * 30 * 1000):
            # MQTT-palvelin ei ole raportoinut yli puoleen tuntiin
            raportoi_virhe("MQTT-palvelinta ei ole nahty: %s sekuntiin."
                           % (utime.ticks_diff(utime.ticks_ms(), mqtt_viimeksi_nahty)) > (60 * 30 * 100))
            restart_and_reconnect()


def main():
    pir = LiikeTunnistin(PIR_PINNI, 2)  # viive sekunneissa
    loop = asyncio.get_event_loop()
    loop.create_task(pir.liike_looppi())
    loop.create_task(pir.laheta_status())
    loop.create_task(pir.tarkista_viesti())
    loop.create_task(pir.uptime_looppi())
    try:
        mqtt_palvelin_yhdista()
        tarkista_virhetiedosto()
        # statuskyselya varten
        client.set_callback(tarkista_uptime)
        # Tilataan brokerin lahettamat sys-viestit ja nollataan aikalaskuri
        client.subscribe("$SYS/broker/bytes/#")
    except AttributeError:
        pass

    while True:
        try:
            loop.run_until_complete(pir.liike_looppi())
            loop.run_until_complete(pir.laheta_status())
            loop.run_until_complete(pir.tarkista_viesti())
            loop.run_until_complete(pir.uptime_looppi())
            time.sleep(0.01)
        except KeyboardInterrupt:
            raise


if __name__ == "__main__":
    main()
