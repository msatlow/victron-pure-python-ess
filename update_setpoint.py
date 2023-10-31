#! /usr/bin/python3

import serial
import paho.mqtt.client as mqtt
import json
from multiplus2 import MultiPlus2
import time
import configparser
import traceback
import argparse

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

    def update_bms_soc(self, bms_soc):
        self.bms_soc=bms_soc
        self.last_bms_soc_data=time.time()


    def update_sm_power(self, sm_power):
        # multiplus2
        if not self.mp2:
            print("no mp2")
            return
        self.mp2.update()
        print(self.mp2.data)
        data=self.mp2.data.copy()


        if not self.last_bms_soc_data or time.time()-self.last_bms_soc_data > 300:  # last bms data older than 5 minutes
            self.bms_soc=data.get('soc',0)
            print(f"no bms data, use mp2 data {self.bms_soc}")

        self.mp2_power_old=self.mp2_power
    #                mp2_power=pid(sm_power)

        self.mp2_power=int(self.mp2_power+(sm_power*0.3))
        
        # limit increase/decrease to 400W (MAX_VICTRON_RAMP)
        if self.mp2_power>self.mp2_power_old+MAX_VICTRON_RAMP:
            self.mp2_power=self.mp2_power_old+MAX_VICTRON_RAMP
        if self.mp2_power<self.mp2_power_old-MAX_VICTRON_RAMP:
            self.mp2_power=self.mp2_power_old-MAX_VICTRON_RAMP


        print(f"mp2_power={self.mp2_power}, old: {self.mp2_power_old} sum: {sm_power}")
        if self.mp2_power>float(self.config['VICTRON']['MAX_CHARGE']):
            self.mp2_power=float(self.config['VICTRON']['MAX_CHARGE'])
        if self.mp2_power< -1*float(self.config['VICTRON']['MAX_INVERT']):
            self.mp2_power=-1*float(self.config['VICTRON']['MAX_INVERT'])

        data['mp2_power_request']=self.mp2_power
        if data.get('inv_p',0) >=0:
            data['inv_p_in']=data.get('inv_p',0)
            data['inv_p_out']=0
        else:
            data['inv_p_out']=data.get('inv_p',0)*-1
            data['inv_p_in']=0

        bat_u=data.get('bat_u',0)

        rc=self.mqtt_client.publish(self.config['VICTRON']['topic'], json.dumps(data))
        print(rc)


#        batu_hyst=52.3 - 0.5 if self.mp2_invert else 0
#        if self.bms_soc < 21 and data.get('bat_u',0)>batu_hyst:
#            print(f"soc {self.bms_soc} too low but battery full {data.get('bat_u')}")
#            self.bms_soc=21

        print(f"mp2_power={self.mp2_power}, soc: {self.bms_soc}, bat_u: {bat_u}")
        if self.mp2_power>0:
            max_soc_hyst=float(self.config['VICTRON']['MAX_SOC']) + (float(self.config['VICTRON']['SOC_HYSTERESIS']) if self.mp2_charge else 0)
            if self.bms_soc < max_soc_hyst:
                print(f"wakeup and set power {self.mp2_power}")
                self.mp2.wakeup()
            #  mp2.vebus.set_power(mp2_power)
                self.mp2.command(int(self.mp2_power))
                self.mp2_charge=True
                self.mp2_invert=False
            else:
                print(f"battery full not {self.bms_soc} < {max_soc_hyst}")
                self.mp2.command(0)
                self.mp2_charge=False
                self.mp2_invert=False
        else:
            min_soc_hyst = float(self.config['VICTRON']['MIN_SOC']) - (float(self.config['VICTRON']['SOC_HYSTERESIS']) if self.mp2_invert else 0)
            if self.bms_soc > min_soc_hyst :
                print(f"set power {self.mp2_power}")

                self.mp2.command(int(self.mp2_power))
                self.mp2_charge=False
                self.mp2_invert=True
            else:
                print(f"battery empty not {self.bms_soc} > {min_soc_hyst}")
                self.mp2.command(0)
                self.mp2_charge=False
                self.mp2_invert=False




def on_message(client, set_point_class, message):
    print(f"message received topic: {message.topic} {str(message.payload.decode('utf-8'))}")
    try:
        data=json.loads(str(message.payload.decode("utf-8")))

        if message.topic == set_point_class.config['SMARTMETER']['topic']:
            print(f"update from smartmeter: {data['power']}")
            set_point_class.update_sm_power(data['power']*-1)
        elif message.topic == set_point_class.config['BMS1']['topic']:
            print(f"update from bms1: soc: {data['soc']}, voltage: {data['voltage']}")
            set_point_class.update_bms_soc(data['soc'])
        else:
            print(f"unknown topic {message.topic}")
            print(f"not {set_point_class.config['SMARTMETER']['topic']}")
    except Exception as ex:
        print(ex)
        traceback.print_exc()


# main program
def main():

    parser = argparse.ArgumentParser()
    parser.add_argument("--config", help="config.ini file", default="config.ini")
    args = parser.parse_args()


    config = configparser.ConfigParser()
    config.read(args.config)

    client = mqtt.Client("UPDATE_SETPOINT")
    if config['MQTT'].get('user'):
        print("mqtt password given")
        client.username_pw_set(config['MQTT']['user'], config['MQTT']['password'])
    client.on_message = on_message
    print(f"connect to mqtt server {config['MQTT']['host']}")
    client.connect(config['MQTT']['host'], int(config['MQTT']['port']))
    print(f"subscribe {config['SMARTMETER']['topic']}")
    client.subscribe(config['SMARTMETER']['topic'])
    print(f"subscibe {config['BMS1']['topic']}")
    client.subscribe(config['BMS1']['topic'])
    set_point_class=SetPoint(client, config)
    client.user_data_set(set_point_class)


    #client.subscribe("#")

    print("start loop")
    client.loop_forever()

if __name__ == '__main__':
    main()

