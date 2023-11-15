#! bin/python3

import serial, time
import paho.mqtt.client as mqtt
import json
import configparser
import argparse
import decypher

key = "0b3ad6806f99976388059296a3e86ecb"
dec = decypher.decypher(key)

# parser = argparse.ArgumentParser()
# parser.add_argument("--config", help="config.ini file", default="config.ini")
# args = parser.parse_args()

# config = configparser.ConfigParser()
# config.read(args.config)
# key=config['SMARTMETER']['aes_key']
# device=config['SMARTMETER']['country_code']

# client = mqtt.Client("smartmeter")

# if config['MQTT'].get('user'):
#     client.username_pw_set(config['MQTT']['user'], config['MQTT']['password'])
# client.connect(config['MQTT']['host'], int(config['MQTT']['port']))
# client.loop_start()

client = mqtt.Client()
client.connect("localhost", 1883, 60)

while 1:
    print("opening serial interface")
    try:
        # ser=serial.Serial(config['SMARTMETER']['serial_port'], baudrate=int(config['SMARTMETER']['serial_baudrate']), timeout=1)
        ser=serial.Serial("/dev/ttyAMA0",baudrate=115200)

        count=0
        while(1):
            junk1=ser.read_until(expected=b'\x7e')
            junk2=ser.read_until(expected=b'\xa0')
            raw=ser.read(122)
            print(len(raw), end=' ')
            data = dec.decrypt(b'\x7e\xa0'+raw)

            print(data)


            #data={
            #    "power_in": pin,
            #    "power_out": pout,
            #    "power": pin-pout,
            #    "power_unit": "W",
            #    "total_in": sin,
            #    "total_out": sout,
            #    "total_unit": "KWh",
            #}
            #rc=client.publish(config['SMARTMETER']['TOPIC'], json.dumps(data))
            rc=client.publish('tele/smartmeter/state', json.dumps(data))


            dspl = {"title": "Smartmeter",
                    "color": 24555,
                    "main": {"unit": "W",
                        "PwrSM": data["power"]
                        },
                    "stand": {
                        "unit": "KWh",
                        "In": "{:.1f}".format(data["total_in"]),
                        "Out": "{:.1f}".format(data["total_out"])
                    }
                    }
            client.publish("display", json.dumps(dspl))
            

  

    except Exception as ex:
        print(ex)
        print(raw)
        time.sleep(1)
    finally:
        if ser:
            ser.close()
