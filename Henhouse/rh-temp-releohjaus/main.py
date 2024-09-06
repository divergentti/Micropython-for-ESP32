# tarkoitettu ESP32-Wroom-32 NodeMCU:lle
# Lukee DHT22-anturia ja ohjaa 2-kanavaista reletta
# Parametrit tuodaan parametrit.py-tiedostosta
# Yksi ledin vilaus = toiminta alkaa
# Kaksi ledin vilautusta = toiminta saatettu loppuun
# 10 ledin vilautusta = virhe!
# 
# Jari Hiltunen 13.6.2020
import time
import utime
import machine
import dht
from machine import Pin
from umqttsimple import MQTTClient
import network
# verkon toiminnan tarkastamista varten
# Raspberry WiFi on huono ja lisaksi raspin pitaa pingata ESP32 jotta yhteys toimii!
sta_if = network.WLAN(network.STA_IF)

# tuodaan parametrit tiedostosta parametrit.py
from parametrit import CLIENT_ID, MQTT_SERVERI, MQTT_PORTTI, MQTT_KAYTTAJA, \
    MQTT_SALASANA, DHT22_LAMPO, DHT22_KOSTEUS, RELE_OHJAUS, PINNI_NUMERO, \
    DHT22_LAMPO_KORJAUSKERROIN, DHT22_KOSTEUS_KORJAUSKERROIN, \
    RELE1PINNI, RELE2PINNI, ANTURI_LUKUVALI, RELE_LUKUVALI

# dht-kirjasto tukee muitakin antureita kuin dht22
anturi = dht.DHT22(Pin(PINNI_NUMERO))
# virhelaskurin idea on tuottaa bootti jos jokin menee pieleen liian usein
anturivirhe = 0 # virhelaskuria varten
anturi_looppi_aika = time.time() # edellinen kerta kun anturi on luettu
relevirhe = 0 # virhelaskuria varten
rele_looppi_aika = time.time() # edellinen kerta kun rele on luettu
edellinen_releviesti = 0 # edellinen releen tilaviesti
client = MQTTClient(CLIENT_ID, MQTT_SERVERI, MQTT_PORTTI, MQTT_KAYTTAJA, MQTT_SALASANA)

def ratkaise_aika():
    (vuosi, kuukausi, kkpaiva, tunti, minuutti, sekunti, viikonpva, vuosipaiva) = utime.localtime()
    paivat = {0: "Ma", 1: "Ti", 2: "Ke", 3: "To", 4: "Pe", 5: "La", 6: "Su"}
    kuukaudet = {1: "Tam", 2: "Hel", 3: "Maa", 4: "Huh", 5: "Tou", 6: "Kes", 7: "Hei", 8: "Elo",
              9: "Syy", 10: "Lok", 11: "Mar", 12: "Jou"}
    #.format(paivat[viikonpva]), format(kuukaudet[kuukausi]),
    aika = "%s.%s.%s klo %s:%s:%s" % (kkpaiva, kuukausi, \
           vuosi, "{:02d}".format(tunti), "{:02d}".format(minuutti), "{:02d}".format(sekunti))
    return aika


def mqtt_palvelin_yhdista():
    aika = ratkaise_aika()
    if sta_if.isconnected():
        try:
            client.connect()
        except OSError as e:

            print("% s:  Ei voida yhdistaa! " % aika)
            client.disconnect()
            time.sleep(10)
            restart_and_reconnect()
            return False
        # releen ohjaus
        client.set_callback(rele_tila)
        client.subscribe(RELE_OHJAUS)
        return True
    else:
        print("%s: Yhteys on poikki! " % aika)
        # client.disconnect()
        restart_and_reconnect()
        return False


def rele_tila(rele_ohjaus, msg):
    global edellinen_releviesti
    aika = ratkaise_aika()
    # Huom! Releet kytketty NC (Normally Closed) jolloin 0 = on
    # Mikali rele kytketty NO (Normally Open), arvo 1 = on
    # Pinni jolla ohjataan rele #1
    rele1 = Pin(RELE1PINNI, Pin.OUT)
    # Pinni jolla ohjataan rele #2
    rele2 = Pin(RELE2PINNI, Pin.OUT)
    # 0 = molemmat pois
    # 1 = rele 1 on, rele 2 off
    # 2 = molemmat on
    # 3 = rele 1 off, rele 2 on
    print((rele_ohjaus, msg))
    # testataan onko tullut uusi arvo vai ei
    if edellinen_releviesti == msg:
        print("%s: Skipataan kun tila onkin sama kuin ennen..." % aika)
        return
    if rele_ohjaus == RELE_OHJAUS and msg == b'0':
        print('%s: Laita kaikki releet off' % aika)
        rele1.value(1)
        rele2.value(1)
        edellinen_releviesti = msg
    if rele_ohjaus == RELE_OHJAUS and msg == b'1':
        print('%s: Laita rele 1 on, rele 2 off' % aika)
        rele1.value(0)
        rele2.value(1)
        edellinen_releviesti = msg
    if rele_ohjaus == RELE_OHJAUS and msg == b'2':
        print('%s: Laita molemmat releet on' % aika)
        rele1.value(0)
        rele2.value(0)
        edellinen_releviesti = msg
    if rele_ohjaus == RELE_OHJAUS and msg == b'3':
        print('%s: Laita rele 1 off, rele 2 on' % aika)
        rele1.value(1)
        rele2.value(0)
        edellinen_releviesti = msg
    vilkuta_ledi(2)


def lue_releen_status():
    global relevirhe
    aika = ratkaise_aika()
    vilkuta_ledi(1)
    print('%s: Tarkistetaan onko uutta releen ohjaustietoa.' % aika)
    if sta_if.isconnected():
        try:
            client.check_msg()
        except OSError as e:
            print("%s: Releviestin lukuvirhe!" % aika)
            relevirhe = relevirhe + 1
            return False
        vilkuta_ledi(2)
        relevirhe = 0
        return True
    else:
        print("%s: Yhteys on poikki! " % aika)
        client.disconnect()
        restart_and_reconnect()
        return False


def lue_lampo_ja_yhdista():
    global anturivirhe
    aika = ratkaise_aika()
    vilkuta_ledi(1)
    try:
        anturi.measure()
    except OSError as e:
        print("%s: Sensoria ei voida lukea!" % aika)
        anturivirhe = anturivirhe + 1
        return False
    lampo = anturi.temperature() * DHT22_LAMPO_KORJAUSKERROIN
    kosteus = anturi.humidity() * DHT22_KOSTEUS_KORJAUSKERROIN
    print('Lampo: %3.1f C' % lampo)
    print('Kosteus: %3.1f %%' % kosteus)
    print("%s: Tallenntaan arvot mqtt-palvelimeen %s ..." % (aika,  MQTT_SERVERI))
    lampo = '{:.1f}'.format(lampo)
    kosteus = '{:.1f}'.format(kosteus)
    if sta_if.isconnected():
        try:
            client.publish(DHT22_LAMPO, str(lampo))
        except OSError as e:
            print("%s: Arvoa %s ei voida tallentaa! " % (aika, str(lampo)))
            anturivirhe = anturivirhe + 1
            return False
        try:
            client.publish(DHT22_KOSTEUS, str(kosteus))
        except OSError as e:
            print("%s: Arvoa %s ei voida tallentaa! " % (aika, str(kosteus)))
            anturivirhe = anturivirhe + 1
            return False
        print('%s: Tallennettu %s %s' % (aika, lampo, kosteus))
        anturivirhe = 0
        return True
    else:
        print("%s: Yhteys on poikki!" % aika)
        client.disconnect()
        restart_and_reconnect()
        return False


def restart_and_reconnect():
    aika = ratkaise_aika()
    print('%s: Ongelmia. Boottaillaan 5s kuluttua.' % aika)
    vilkuta_ledi(10)
    time.sleep(5)
    machine.reset()
    # resetoidaan


def vilkuta_ledi(kertaa):
    ledipinni = machine.Pin(2, machine.Pin.OUT)
    for i in range(kertaa):
        ledipinni.on()
        utime.sleep_ms(100)
        ledipinni.off()
        utime.sleep_ms(100)


def anturiluuppi():
    global anturi_looppi_aika
    if anturivirhe < 5:
        aika = ratkaise_aika()
        print("%s: Anturiluupin virhelaskuri: %s" % (aika, anturivirhe))
        try:
            lue_lampo_ja_yhdista()
        except OSError as e:
            print("%s: Anturiluupin virhelaskuri: %s" % (aika, anturivirhe))
            # Virheita liikaa
            restart_and_reconnect()
        anturi_looppi_aika = time.time()
    return


def releluuppi():
    global rele_looppi_aika
    if relevirhe < 5:
        aika = ratkaise_aika()
        print("%s: Releloopin virhelaskuri: %s" % (aika, relevirhe))
        try:
            lue_releen_status()
        except OSError as e:
            print("%s: Releloopin virhelaskuri: %s" % (aika, relevirhe))
            # Virheita liikaa
            restart_and_reconnect()
        rele_looppi_aika = time.time()
    return

try:
    mqtt_palvelin_yhdista()
except OSError as e:
    aika = ratkaise_aika()
    print("%s: Ei onnistunut yhteys mqtt-palvelimeen %s" % (aika, MQTT_SERVERI))
    restart_and_reconnect()

try:
    while True:
        if (relevirhe >= 5) or (anturivirhe >= 5): restart_and_reconnect() # liikaa virheita
        kulunut_anturi_aika = (time.time() - anturi_looppi_aika)
        kulunut_rele_aika = (time.time() - rele_looppi_aika)
        if (RELE_LUKUVALI <= ANTURI_LUKUVALI) and (kulunut_rele_aika >= RELE_LUKUVALI): releluuppi()
        if (RELE_LUKUVALI > ANTURI_LUKUVALI) and (kulunut_rele_aika >= RELE_LUKUVALI): releluuppi()
        if (ANTURI_LUKUVALI <= RELE_LUKUVALI) and (kulunut_anturi_aika >= ANTURI_LUKUVALI): anturiluuppi()
        if (ANTURI_LUKUVALI > RELE_LUKUVALI) and (kulunut_anturi_aika >= ANTURI_LUKUVALI): anturiluuppi()

except KeyboardInterrupt:
    raise
except Exception:
    restart_and_reconnect()
