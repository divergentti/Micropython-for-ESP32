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
    2.11.2020:  Tehty objektimallinen scripti ja viivemahdolisuus viesteille. Oletus 5s.
"""
import time
import utime
import machine  # tuodaan koko kirjasto
from machine import Pin
from umqttsimple import MQTTClient
import gc
import os
# tuodaan parametrit tiedostosta parametrit.py
from parametrit import CLIENT_ID, MQTT_SERVERI, MQTT_PORTTI, MQTT_KAYTTAJA, \
    MQTT_SALASANA, PIR_PINNI, AIHE_LIIKETUNNISTIN, AIHE_VIRHEET
# tuodaan bootis wifi-ap:n objekti
from boot import wificlient_if


client = MQTTClient(CLIENT_ID, MQTT_SERVERI, MQTT_PORTTI, MQTT_KAYTTAJA, MQTT_SALASANA)


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
    global client

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

    def laheta_status(self):
        """ Tarkistetaan tuleeko ilmoittaa """
        if (utime.time()-self.ilmoitettu_aika) >= self.viive:
            if self.ilmoitettu is False and self.tila != self.edellinen_tila:
                try:
                    client.publish(AIHE_LIIKETUNNISTIN, str(self.tila), qos=1, retain=True)
                    self.ilmoitettu = True
                    self.edellinen_tila = self.tila
                    self.ilmoitettu_aika = utime.time()
                    print("%s: Ilmoitettu tila: %s" % (utime.time(), self.tila))
                except OSError:
                    restart_and_reconnect()
        else:
            self.ilmoitettu = False

    def liike_looppi(self):
        self.tila = self.pinni.value()
        if self.tila == 1:
            self.on_aika = utime.time()
            self.liiketta = True
        if self.tila == 0:
            self.off_aika = utime.time()
            self.liiketta = False


def paalooppi():
    pir = LiikeTunnistin(PIR_PINNI, 5)  # viive sekunneissa

    try:
        mqtt_palvelin_yhdista()
        tarkista_virhetiedosto()
        # statuskyselya varten
    except AttributeError:
        pass

    while True:
        try:
            pir.liike_looppi()
            if pir.liiketta is True:
                pir.laheta_status()
            elif pir.liiketta is False:
                pir.laheta_status()
            time.sleep(0.1)
        except OSError:
            restart_and_reconnect()
        except KeyboardInterrupt:
            raise


if __name__ == "__main__":
    paalooppi()
