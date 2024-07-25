These scripts are used for I2C connected OLED display, BME680 temperature/rh/pressure/voc sensor
MH-Z19B CO2 NDIR-sensor, PMS9103M particle sensor.

Values could be transferred by MQTT to the MQTT broker and from the broker to the Influxdb etc.

I2C for the OLED and BME680 are connected to SDA = Pin21 and SCL (SCK) = Pin22.
Use command i2c.scan() to check which devices respond from the I2C channel.

MH-Z19B and PMS9103M are connected to UART1 and UART2.

PMS9103M (9003M) datasheet https://evelta.com/content/datasheets/203-PMS9003M.pdf

Pinout (ledge upwards, PIN1 = right):
PIN1 = VCC = 5V
PIN2 = GND
PIN3 = SET (TTL 3.3V = normal working, GND = sleeping) = 4 *
PIN4 = RXD (3.3V) = 17
PIN5 = TXD (3.3V) = 16
PIN6 = RESET = 2 *
7,8 N/C.

MH-Z19B databseet: https://www.winsen-sensor.com/d/files/infrared-gas-sensor/mh-z19b-co2-ver1_0.pdf

Pinout (do not use 2,3 tx/rx otherwise pytool fails):
Vin = 5V
GND = GND
RX = 32
TX = 33

Program read sensor values once per second, rounds them to 1 decimal with correction values, then calculates averages.
Averages are sent to the MQTT broker.

For webrepl, remember to execute import webrepl_setup one time.

Asyncronous code.
