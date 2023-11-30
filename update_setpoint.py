#! /usr/bin/python3

import serial
import paho.mqtt.client as mqtt
import json
from multiplus2 import MultiPlus2
import time
import configparser
import traceback
import argparse
import math
import logging
import logging.handlers
import sys
import signal
import datetime

MAX_VICTRON_RAMP=400

class SetPoint:
    def __init__(self, mqtt_client, config):
        self.mp2=MultiPlus2(config['VICTRON']['serial_port'])
        self.mp2_power=0
        self.mp2_power_old=0
        self.mp2_charge=False
        self.mp2_invert=False
        self.bms_soc=None
        self.last_bms_soc_data=None
        self.mqtt_client=mqtt_client
        self.config=config
        self.battery_empty_ts=None
        self.mp2_standby=False
        self.mp2_device_state_name=None
        self.mppt_topic=None
        self.mppt_power=0
        self.last_mppt_power=None
        self.counter=0
        

    def update_bms_soc(self, bms_soc):
        self.bms_soc=bms_soc
        self.last_bms_soc_data=time.time()

    def update_mppt(self, data):
        self.mppt_power=data.get('PPV',0)
        self.last_mppt_power=time.time()
        logging.info(f"mppt power: {self.mppt_power}")

    def get_max_charge(self):
        return float(self.config['VICTRON']['MAX_CHARGE'])

    def get_max_invert(self):
        max_invert=float(self.config['VICTRON']['MAX_INVERT'])
        min_soc=float(self.config['VICTRON']['MIN_SOC'])

        max_invert2=math.tanh(((self.bms_soc-min_soc) / 10))*max_invert

        if self.last_mppt_power and time.time()-self.last_mppt_power < 20:  # we have current value
            if self.mppt_power-160 > max_invert2:
                logging.debug(f"increate max_invert2 to {max_invert2} because of mppt power {self.mppt_power}")
                max_invert2=self.mppt_power - 160

        return max(max_invert2, 300)       # mindesten 300 Watt Leistung


    def set_mp2_setpoint(self, setpoint, standby=False):

        if standby:
            if not self.battery_empty_ts:
                self.battery_empty_ts=time.time()

            if self.battery_empty_ts and time.time()-self.battery_empty_ts > 300:
                logging.warning("battery empty for 5 minutes, go to standby")
                self.mp2.sleep()
                self.mp2.command(0)
                self.mp2_standby=True
                self.battery_empty_ts=None
            # else:
            #     self.mp2.command(0)               # required???

            
        else:
            if self.mp2_standby:
                logging.warning("wakeup mp2 from standby")
                self.mp2.wakeup()
                self.mp2_standby=False
            
            if self.mp2_device_state_name=='off':
                logging.warning("mp2 is off, wakeup")
                self.mp2.wakeup()

            self.mp2.command(int(setpoint))

        if setpoint>0:
            self.mp2_charge=True
            self.mp2_invert=False
        elif setpoint<0:
            self.mp2_charge=False
            self.mp2_invert=True
        else:
            self.mp2_charge=False
            self.mp2_invert=False

    def custom_update(self, data):
        dspl = {"title": "Victron",
            "color": 22142,
            "main": {"unit": "%",
                "Bat": data.get("soc")
                },
            "stand0": {
                "unit": "",
                "State": f"{data.get('state')}/{data.get('device_state_id')}",
            },
            "stand1": {
                "unit": "W",
                "Bat": "{:.1f}".format(data.get("bat_p", 0)),
            },
            "stand2": {
                "unit": "A",
                "Bat": "{:.1f}".format(data.get("bat_i", 0)),
            }
        }
        self.mqtt_client.publish("display", json.dumps(dspl))
        print(json.dumps(dspl))


    def update_sm_power(self, sm_power):
        # multiplus2
        if not self.mp2:
            logging.error("no mp2")
            return
        self.mp2.update()
        logging.info(self.mp2.data)
        data=self.mp2.data.copy()
        self.mp2_device_state_name=data.get('device_state_name',None)


        if not self.last_bms_soc_data or time.time()-self.last_bms_soc_data > 60:  # last bms data older than 5 minutes
            self.bms_soc=data.get('soc',0)
            logging.debug(f"no bms data, use mp2 data {self.bms_soc}")

        self.mp2_power_old=self.mp2_power
    #                mp2_power=pid(sm_power)

    #    self.mp2_power=int(self.mp2_power+(sm_power*0.3))
        if abs(self.mp2_power)>100:
            self.mp2_power=int(self.mp2_power+(sm_power*0.3))
        else:
            self.mp2_power=int(self.mp2_power+(sm_power*0.1))

        
        # limit increase/decrease to 400W (MAX_VICTRON_RAMP)
        if self.mp2_power>self.mp2_power_old+MAX_VICTRON_RAMP:
            self.mp2_power=self.mp2_power_old+MAX_VICTRON_RAMP
        if self.mp2_power<self.mp2_power_old-MAX_VICTRON_RAMP:
            self.mp2_power=self.mp2_power_old-MAX_VICTRON_RAMP


        logging.info(f"mp2_power={self.mp2_power}, old: {self.mp2_power_old} sum: {sm_power}")
        
        if self.mp2_power>self.get_max_charge():
            self.mp2_power=self.get_max_charge()
        if self.mp2_power< -1* self.get_max_invert():
            self.mp2_power=-1* self.get_max_invert()

        data['mp2_power_request']=self.mp2_power
        if data.get('inv_p',0) >=0:
            data['inv_p_in']=data.get('inv_p',0)
            data['inv_p_out']=0
        else:
            data['inv_p_out']=data.get('inv_p',0)*-1
            data['inv_p_in']=0

        bat_u=data.get('bat_u',0)

        rc=self.mqtt_client.publish(self.config['VICTRON']['topic'], json.dumps(data))
        logging.debug(rc)


#        batu_hyst=52.3 - 0.5 if self.mp2_invert else 0
#        if self.bms_soc < 21 and data.get('bat_u',0)>batu_hyst:
#            logging.info(f"soc {self.bms_soc} too low but battery full {data.get('bat_u')}")
#            self.bms_soc=21

        logging.info(f"mp2_power={self.mp2_power}, soc: {self.bms_soc}, bat_u: {bat_u}")
        if self.mp2_power>0:
            max_soc_hyst=float(self.config['VICTRON']['MAX_SOC']) + (float(self.config['VICTRON']['SOC_HYSTERESIS']) if self.mp2_charge else 0)
            if self.bms_soc < max_soc_hyst:
                logging.info(f"wakeup and set power {self.mp2_power}")
            #  mp2.vebus.set_power(mp2_power)
                self.set_mp2_setpoint(int(self.mp2_power), standby=False)
                # self.mp2_charge=True
                # self.mp2_invert=False
            else:
                logging.info(f"battery full not {self.bms_soc} < {max_soc_hyst}")
                self.set_mp2_setpoint(0, standby=False)
                # self.mp2_charge=False
                # self.mp2_invert=False
        else:
            min_soc_hyst = float(self.config['VICTRON']['MIN_SOC']) - (float(self.config['VICTRON']['SOC_HYSTERESIS']) if self.mp2_invert else 0)
            if self.bms_soc > min_soc_hyst :
                logging.info(f"set power {self.mp2_power}")

                self.set_mp2_setpoint(int(self.mp2_power))
                # self.mp2_charge=False
                # self.mp2_invert=True
            else:
                logging.info(f"battery empty not {self.bms_soc} > {min_soc_hyst}")
                self.set_mp2_setpoint(0, True)
                # self.mp2_charge=False
                # self.mp2_invert=False

        try:
            self.custom_update(data)
        except Exception as ex:
            logging.warning(f"unable to call custom code, got {ex}", exc_info=True) 

        self.counter+=1

        if self.counter > 10:
            self.touch_file()
            self.counter=0

    def touch_file(self):
        f = open("watchdog.txt", "w")
        f.write(f"Watchdog on {datetime.datetime.now()}")
        f.close()


def on_message(client, set_point_class, message):
    logging.debug(f"message received topic: {message.topic} {str(message.payload.decode('utf-8'))}")
    try:
        data=json.loads(str(message.payload.decode("utf-8")))

        if message.topic == set_point_class.config['SMARTMETER']['topic']:
            logging.debug(f"update from smartmeter: {data['power']}")
            set_point_class.update_sm_power(data['power']*-1)
        elif message.topic == set_point_class.config['BMS1']['topic']:
            logging.info(f"update from bms1: soc: {data['soc']}, voltage: {data['voltage']}")
            set_point_class.update_bms_soc(data['soc'])
        elif message.topic == client.mpp_topic:
            set_point_class.update_mppt(data)
        else:
            logging.info(f"unknown topic {message.topic}")
            logging.info(f"not {set_point_class.config['SMARTMETER']['topic']}")
    except Exception as ex:
        logging.error(ex, exc_info=True)

def read_config():
    global config
    global config_file
    if not config:
        config = configparser.ConfigParser()
    config.read(config_file)

def signal_hub_handler(signal, frame):
    logging.warning("got hub signal")
    read_config()



# global variables
config=None
config_file=None

# main program
def main():
    global config_file
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', stream=sys.stdout)
    sysloghandler=logging.handlers.SysLogHandler(address='/dev/log')
    sysloghandler.setLevel(logging.WARNING)
    logging.getLogger().addHandler(sysloghandler)

    logging.warning("start update_setpoint.py")

    parser = argparse.ArgumentParser()
    parser.add_argument("--config", help="config.ini file", default="config.ini")
    args = parser.parse_args()
    config_file=args.config

    read_config()

    client = mqtt.Client("UPDATE_SETPOINT")
    if config['MQTT'].get('user'):
        logging.info("mqtt password given")
        client.username_pw_set(config['MQTT']['user'], config['MQTT']['password'])
    client.on_message = on_message

    logging.info(f"connect to mqtt server {config['MQTT']['host']}")
    client.connect(config['MQTT']['host'], int(config['MQTT']['port']))
    logging.info(f"subscribe {config['SMARTMETER']['topic']}")
    client.subscribe(config['SMARTMETER']['topic'])
    logging.info(f"subscibe {config['BMS1']['topic']}")
    client.subscribe(config['BMS1']['topic'])

    if config['VICTRON'].get('mppt_topic'):
        client.mpp_topic=config['VICTRON']['mppt_topic']
        client.subscribe(config['VICTRON']['mppt_topic'])

    set_point_class=SetPoint(client, config)
    client.user_data_set(set_point_class)


    #client.subscribe("#")

    signal.signal(signal.SIGHUP, signal_hub_handler)


    logging.info("start loop")
    client.loop_forever()

if __name__ == '__main__':
    main()
