""" 24.07.2020 Jari Hiltunen

    MQ135-sensorille:
        ESP32:n ADC-pinnin V on 0.0 - 1.0 V ja kaikki sen yli palauttaa 4095!
        Tee vastuksilla splitteri, esimerkiksi 5V:sta R1=40K ja R2=10K josta
        40K menee 5V ja 10K maihin. Tasta valista otat lahdon ADC:lle.

    Sensorin datasheetilta:
    - Rs 30 KOhm - 200 KOhm
    - RL = 20 KOhm
    - Ro = 100 ppm NH3 puhtaassa ilmassa
    - O2 standardi 21 %, Temp 20C, Rh 65 %
    - Rh vaikutus Rh ja lampo: Rs/Ro = 1 (20C/33 % Rh), Rs/Ro = 1.7 (-10C/33 % Rh)
    - Rh 33 % -> 85 % vaikutus Rs/Ro = 0.1
    - Scopet NH3 = 10 - 300 ppm
    - Bentseeni 10 - 1000 ppm
    - Alkoholi 10 - 300 ppm

    Anturin tulee antaa asettua noin vuorokausi ennen luotettavia arvoja!
    Kalibroinnin voi tehdä pitämällä anturin ulkoilmassa ja vertaamalla mikä on CO2 globaali arvo.

    DHT22-anturille:
    - lämpötila ja kosteus luetaan parametrit.py - PINNI_NUMERO mukaisesta paikasta
    - lämpötilaarvo tulee olla välillä - 40 + 100 astetta, muuten anturi tulkitaan vialliseksi
    - kosteusarvon tulee olla välillä 0 - 100, muuten anturi tulkitaan vialliseksi

    Muutokset:
    12.10.2020: Korjattu client-connect

"""
import math  # tarvitaan laskennassa
import time
import utime
import machine  # tuodaan koko kirjasto
from machine import Pin
from machine import ADC
from umqttsimple import MQTTClient
import network
import gc
import dht  # DHT22 jne antureille

# tuodaan parametrit tiedostosta parametrit.py
from parametrit import CLIENT_ID, MQTT_SERVERI, MQTT_PORTTI, MQTT_KAYTTAJA, \
    MQTT_SALASANA, SISA_PPM, MQ135_PINNI, DHT22_LAMPO, DHT22_KOSTEUS, \
    DHT22_LAMPO_KORJAUSKERROIN, DHT22_KOSTEUS_KORJAUSKERROIN, PINNI_NUMERO

gc.enable()  # aktivoidaan automaattinen roskankeruu

""" asetetaan hitaampi kellotus 20MHz, 40MHz, 80Mhz, 160MHz or 240MHz 
    Hitaammalla kellotuksella prosessori lämpenee vähemmän """
machine.freq(80000000)
print("Prosessorin nopeus asetettu: %s" % machine.freq())

# Globaalit
lampo = 0
kosteus = 0
anturivirhe = 0

sta_if = network.WLAN(network.STA_IF)

""" mtqq-clientin yhdistaminen """
client = MQTTClient(CLIENT_ID, MQTT_SERVERI, MQTT_PORTTI, MQTT_KAYTTAJA, MQTT_SALASANA)
"""  dht-kirjasto tukee muitakin antureita kuin dht22 """
anturi = dht.DHT22(Pin(PINNI_NUMERO))


class MQ135(object):
    """
    Source rubfi: https://raw.githubusercontent.com/rubfi/MQ135/master/mq135.py

    Modified for the ESP32 by Divergentti / Jari Hiltunen

    Micropython library for dealing with MQ135 gas sensor
    Based on Arduino Library developed by G.Krocker (Mad Frog Labs)
    and the corrections from balk77 and ViliusKraujutis

    More info:
        https://hackaday.io/project/3475-sniffing-trinket/log/12363-mq135-arduino-library
        https://github.com/ViliusKraujutis/MQ135
        https://github.com/balk77/MQ135
    """
    """ Class for dealing with MQ13 Gas Sensors """
    # The load resistance on the board
    RLOAD = 10.0
    # Calibration resistance at atmospheric CO2 level
    RZERO = 76.63
    # Parameters for calculating ppm of CO2 from sensor resistance
    PARA = 116.6020682
    PARB = 2.769034857

    # Parameters to model temperature and humidity dependence
    CORA = 0.00035
    CORB = 0.02718
    CORC = 1.39538
    CORD = 0.0018
    CORE = -0.003333333
    CORF = -0.001923077
    CORG = 1.130128205

    # Atmospheric CO2 level for calibration purposes
    ATMOCO2 = 397.13

    def __init__(self, pin):
        self.pin = pin

    def get_correction_factor(self, temperature, humidity):
        """Calculates the correction factor for ambient air temperature and relative humidity

        Based on the linearization of the temperature dependency curve
        under and above 20 degrees Celsius, asuming a linear dependency on humidity,
        provided by Balk77 https://github.com/GeorgK/MQ135/pull/6/files
        """

        if temperature < 20:
            return self.CORA * temperature * temperature - self.CORB * temperature + self.CORC \
                             - (humidity - 33.) * self.CORD

        return self.CORE * temperature + self.CORF * humidity + self.CORG

    def get_resistance(self):
        """Returns the resistance of the sensor in kOhms // -1 if not value got in pin"""
        adc = ADC(self.pin)
        value = adc.read()
        if value == 0:
            return -1

        return (4095./value - 1.) * self.RLOAD  # ESP32 maksimi, ESP8266:lle arvo on 1023

    def get_corrected_resistance(self, temperature, humidity):
        """Gets the resistance of the sensor corrected for temperature/humidity"""
        return self.get_resistance() / self.get_correction_factor(temperature, humidity)

    def get_ppm(self):
        """Returns the ppm of CO2 sensed (assuming only CO2 in the air)"""
        return self.PARA * math.pow((self.get_resistance() / self.RZERO), -self.PARB)

    def get_corrected_ppm(self, temperature, humidity):
        """Returns the ppm of CO2 sensed (assuming only CO2 in the air)
        corrected for temperature/humidity"""
        return self.PARA * math.pow((self.get_corrected_resistance(temperature, humidity) / self.RZERO), -self.PARB)

    def get_rzero(self):
        """Returns the resistance RZero of the sensor (in kOhms) for calibratioin purposes"""
        return self.get_resistance() * math.pow((self.ATMOCO2/self.PARA), (1./self.PARB))

    def get_corrected_rzero(self, temperature, humidity):
        """Returns the resistance RZero of the sensor (in kOhms) for calibration purposes
        corrected for temperature/humidity"""
        return self.get_corrected_resistance(temperature, humidity) * math.pow((self.ATMOCO2/self.PARA), (1./self.PARB))


def ratkaise_aika():
    (vuosi, kuukausi, kkpaiva, tunti, minuutti, sekunti, viikonpva, vuosipaiva) = utime.localtime()
    aika = "%s.%s.%s klo %s:%s:%s" % (kkpaiva, kuukausi, vuosi, "{:02d}".format(tunti),
                                      "{:02d}".format(minuutti), "{:02d}".format(sekunti))
    return aika


def mqtt_palvelin_yhdista():
    aika = ratkaise_aika()
    if sta_if.isconnected():
        try:
            client.connect()
        except OSError:
            print("% s:  Ei voida yhdistaa! " % aika)
            time.sleep(10)
            restart_and_reconnect()
            return False
        return True
    else:
        print("%s: Yhteys on poikki! " % aika)
        restart_and_reconnect()
        return False


def lue_ja_tallenna_lampo_ja_kosteus():
    global anturivirhe, lampo, kosteus
    aika = ratkaise_aika()
    try:
        anturi.measure()
    except OSError:
        print("%s: Sensoria ei voida lukea!" % aika)
        anturivirhe = anturivirhe + 1
        if anturi > 5:
            print("Liikaa anturivirheitä!")
            restart_and_reconnect()
        return False
    lampo = anturi.temperature() * DHT22_LAMPO_KORJAUSKERROIN
    kosteus = anturi.humidity() * DHT22_KOSTEUS_KORJAUSKERROIN
    if (lampo < 40) or (lampo > 100):
        anturivirhe = anturivirhe + 1
    if (kosteus < 1) or (kosteus > 100):
        anturivirhe = anturivirhe + 1
    print('Lampo: %3.1f C' % lampo)
    print('Kosteus: %3.1f %%' % kosteus)
    print("%s: Tallenntaan arvot mqtt-palvelimeen %s ..." % (aika,  MQTT_SERVERI))
    lampo = '{:.1f}'.format(lampo)
    kosteus = '{:.1f}'.format(kosteus)
    if sta_if.isconnected():
        try:
            client.publish(DHT22_LAMPO, str(lampo))
        except OSError:
            print("%s: Arvoa %s ei voida tallentaa! " % (aika, str(lampo)))
            anturivirhe = anturivirhe + 1
            return False
        try:
            client.publish(DHT22_KOSTEUS, str(kosteus))
        except OSError:
            print("%s: Arvoa %s ei voida tallentaa! " % (aika, str(kosteus)))
            anturivirhe = anturivirhe + 1
            return False
        print('%s: Tallennettu %s %s' % (aika, lampo, kosteus))
        anturivirhe = 0
        return True
    else:
        print("%s: Yhteys on poikki!" % aika)
        restart_and_reconnect()
        return False


def laheta_ppm_mqtt(ppm):
    aika = ratkaise_aika()
    if sta_if.isconnected():
        try:
            client.publish(SISA_PPM, str(ppm))  # julkaistaan ppm arvo
        except OSError:
            print("% s:  Ei voida yhdistaa! " % aika)
            time.sleep(10)
            restart_and_reconnect()
            return False
        return True
    else:
        print("%s: Yhteys on poikki! " % aika)
        restart_and_reconnect()
        return False


def vilkuta_ledi(kertaa):
    ledipinni = machine.Pin(2, machine.Pin.OUT)
    for i in range(kertaa):
        ledipinni.on()
        utime.sleep_ms(100)
        ledipinni.off()
        utime.sleep_ms(100)


def restart_and_reconnect():
    aika = ratkaise_aika()
    print('%s: Ongelmia. Boottaillaan 5s kuluttua.' % aika)
    vilkuta_ledi(10)
    time.sleep(5)
    machine.reset()
    # resetoidaan


def palauta_ppm():
    global lampo, kosteus
    loopin_alkuaika = utime.time()
    mqtt_palvelin_yhdista()
    lue_ja_tallenna_lampo_ja_kosteus()
    temperature = float(lampo)
    humidity = float(kosteus)
    mq135 = MQ135(Pin(MQ135_PINNI))  # objektin luonti, analogi PIN 0 ESP32 ADC0
    ppm_lista = []  # keskiarvon laskentaa varten
    aika = ratkaise_aika()
    print("%s Luetaan ensimmaiset 60 arvoa listalle kerran sekunnissa ... odota" % aika)
    # looppi
    while True:
        try:
            # luetaan mq-135 sensorilta uusi tieto
            ppm_lista.append(mq135.get_corrected_ppm(temperature, humidity))
        except ValueError:
            pass
        # lasketaan minuutin keskiarvo PPM:lle
        if len(ppm_lista) == 60:
            keskiarvo = sum(ppm_lista) / len(ppm_lista)
            print("Tallennettava keskiarvo on: %s ppm" % keskiarvo)
            """ Tarkistetaan onko looppi toiminut yli vuorokauden, jolloin anturi on kalibroitunut
                ja tämän jälkeen arvioidaan ilmanlaatua """
            print("Looppi toiminnassa %s sekuntia" % (utime.time()-loopin_alkuaika))
            # julkaistaan keskiarvo mqtt ilman arvon tarkistusta
            laheta_ppm_mqtt(keskiarvo)
            ppm_lista.clear()  # nollataan lista
            # Odotetaan uutta lampo ja kosteus
            lue_ja_tallenna_lampo_ja_kosteus()
            temperature = float(lampo)
            humidity = float(kosteus)
            aika = ratkaise_aika()
            print("%s Luetaan seuraavat 60 arvoa listalle... odota" % aika)
        time.sleep(1)  # lukuvali 1s.


if __name__ == "__main__":
    palauta_ppm()
