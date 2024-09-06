""" Asynkroninen mqtt ESP32-Wroom-NodeMCU ja vastaaville (micropython)

    Tämä scripti ohjaa kahta 2 Relay modulea siten, että kun mqtt-kanavasta tulee käsky laittaa rele päälle,
    laitetaan ESP32:lta PIN.OUT tilaan 1.

    Esimerkiksi AIHE1_RELE1 voisi olla 'koti/ulko/valaistusautokatos' josta luettu mqtt-viesti 1 laittaisi
    RELE1_PINNI1 arvoksi 1.

    Arvot tuodaan parametrit.py-tiedostosta.

    MQTT hyödyntää valmista kirjastoa mqtt_as.py joka on ladattavissa:
    https://github.com/peterhinch/micropython-mqtt/tree/master/mqtt_as

    16.10.2020: Jari Hiltunen
"""
import time
import utime
import machine
import uasyncio as asyncio
from machine import Pin
from mqtt_as import MQTTClient
import os
import network
import gc
from mqtt_as import config
# tuodaan parametrit tiedostosta parametrit.py
from parametrit import CLIENT_ID, MQTT_SERVERI, MQTT_PORTTI, MQTT_KAYTTAJA, \
    MQTT_SALASANA, AIHE_VIRHEET, RELE1_PINNI1, RELE1_PINNI2, RELE2_PINNI1, RELE2_PINNI2,\
    AIHE_RELE1_1, AIHE_RELE1_2, AIHE_RELE2_1, AIHE_RELE2_2, SSID1, SALASANA1, SSID2, SALASANA2

kaytettava_salasana = None

if network.WLAN(network.STA_IF).config('essid') == SSID1:
    kaytettava_salasana = SALASANA1
elif network.WLAN(network.STA_IF).config('essid') == SSID2:
    kaytettava_salasana = SALASANA2

config['server'] = MQTT_SERVERI
config['ssid'] = network.WLAN(network.STA_IF).config('essid')
config['wifi_pw'] = kaytettava_salasana

# Luodaan releobjektitHuom! Releet kytketty NC (Normally Closed) jolloin 0 = on
rele1_1 = Pin(RELE1_PINNI1, Pin.OUT)
rele1_2 = Pin(RELE1_PINNI2, Pin.OUT)
rele2_1 = Pin(RELE2_PINNI1, Pin.OUT)
rele2_2 = Pin(RELE2_PINNI2, Pin.OUT)


def raportoi_virhe(virhe):
    # IN: str virhe = virheen tekstiosa
    try:
        tiedosto = open('virheet.txt', "r")
        # mikali tiedosto on olemassa, jatketaan
    except OSError:  # avaus ei onnistu, luodaan uusi
        tiedosto = open('virheet.txt', 'w')
        # virheviestin rakenne: pvm + aika;uptime;laitenimi;ip;virhe;vapaa muisti
    virheviesti = str(ratkaise_aika()) + ";" + str(utime.ticks_ms()) + ";" \
        + str(CLIENT_ID) + ";" + str(network.WLAN(network.STA_IF).ifconfig()) + ";" + str(virhe) +\
        ";" + str(gc.mem_free())
    tiedosto.write(virheviesti)
    tiedosto.close()


def ratkaise_aika():
    (vuosi, kuukausi, kkpaiva, tunti, minuutti, sekunti, viikonpva, vuosipaiva) = utime.localtime()
    aika = "%s.%s.%s klo %s:%s:%s" % (kkpaiva, kuukausi, vuosi, "{:02d}".format(tunti),
                                      "{:02d}".format(minuutti), "{:02d}".format(sekunti))
    return aika


async def conn_han(client):
    await client.subscribe(AIHE_RELE1_1, 1)
    await client.subscribe(AIHE_RELE1_2, 1)
    await client.subscribe(AIHE_RELE2_1, 1)
    await client.subscribe(AIHE_RELE2_2, 1)


async def main(client):
    await client.connect()
    n = 0
    while True:
        await asyncio.sleep(5)
        print('publish', n)
        # If WiFi is down the following will pause for the duration.
        await client.publish('result', '{}'.format(n), qos=1)
        n += 1


def rele_tila(rele_ohjaus, msg, retained):
    aika = ratkaise_aika()
    print((rele_ohjaus, msg))
    # Tarkistetaan mille aiheelle viesti tuli
    # Rele 1 pinni 1
    if rele_ohjaus == AIHE_RELE1_1 and msg == b'0':
        print('%s: %s off' % (aika, AIHE_RELE1_1))
        rele1_1.value(0)
    if rele_ohjaus == AIHE_RELE1_1 and msg == b'1':
        print('%s: %s on' % (aika, AIHE_RELE1_1))
        rele1_1.value(1)
    # Rele 1 pinni 2
    if rele_ohjaus == AIHE_RELE1_2 and msg == b'0':
        print('%s: %s off' % (aika, AIHE_RELE1_2))
        rele1_2.value(0)
    if rele_ohjaus == AIHE_RELE1_2 and msg == b'1':
        print('%s: %s on' % (aika, AIHE_RELE1_2))
        rele1_2.value(1)
    # Rele 2 pinni 1
    if rele_ohjaus == AIHE_RELE2_1 and msg == b'0':
        print('%s: %s off' % (aika, AIHE_RELE2_1))
        rele2_1.value(0)
    if rele_ohjaus == AIHE_RELE2_1 and msg == b'1':
        print('%s: %s on' % (aika, AIHE_RELE2_1))
        rele2_1.value(1)
    # REle 2 pinni 2
    if rele_ohjaus == AIHE_RELE2_2 and msg == b'0':
        print('%s: %s off' % (aika, AIHE_RELE2_2))
        rele2_2.value(0)
    if rele_ohjaus == AIHE_RELE2_2 and msg == b'1':
        print('%s: %s on' % (aika, AIHE_RELE2_2))
        rele2_2.value(1)


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


config['subs_cb'] = rele_tila
config['connect_coro'] = conn_han
config['user'] = MQTT_KAYTTAJA
config['password'] = MQTT_SALASANA
config['port'] = MQTT_PORTTI
tarkista_virhetiedosto()
MQTTClient.DEBUG = True
client = MQTTClient(config)
loop = asyncio.get_event_loop()

try:
    loop.run_until_complete(main(client))
finally:
    client.close()  # Prevent LmacRxBlk:1 error
