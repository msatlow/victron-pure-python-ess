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
import pprint
import vebus_constants

MAX_VICTRON_RAMP=400

# https://github.com/yvesf/ve-ctrl-tool

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
        self.cmd_topic=None
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

            if self.config.getboolean('VICTRON','sleep_enabled', fallback=False):
                if self.battery_empty_ts and time.time()-self.battery_empty_ts > self.config.getint('VICTRON','SLEEP_TIMEOUT', fallback=3600):
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

        # target = 0
        # target_delta = sm_power-target
        # p_factor=0.1+0.2*math.tanh(abs(target_delta/50))
        # self.mp2_power=int(self.mp2_power+(target_delta*p_factor))

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

        if self.mp2_standby and self.mp2_power>0 and sm_power < -50:
            logging.info("mp2 is in standby, but power is less than 100W, keep standby")
            self.mp2_power=0

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

    def get_ram_var_infos(self):
        (soc_sc, soc_offset) = self.mp2.vebus.read_ram_var_info(vebus_constants.RAM_IDS['ChargeState'])
        print(f"soc_sc: {soc_sc}, soc_offset: {soc_offset}")

        (sc, offset) = self.mp2.vebus.read_ram_var_info(vebus_constants.RAM_IDS['UBat'])
        print(f"ubat: soc_sc: {sc}, soc_offset: {offset}")

        (sc, offset) = self.mp2.vebus.read_ram_var_info(vebus_constants.RAM_IDS['UMainsRMS'])
        print(f"UMainsRMS: sc: {sc}, offset: {offset}")



    def fech_data(self):
        self.mp2.update()
        data=self.mp2.data
        print(data)


#        infos=self.get_ram_var_infos()
#        return None

        phase_dict={1:{}, 2:{}, 3:{}}

        for phase in range (1,4):
            print(f"Phase {phase}")
            ac_info = self.mp2.vebus.get_ac_info(phase)
            print(ac_info)
            phase_dict[phase].update({"ac_info": ac_info })

        for page in range(0,4):
            ids = list(filter(lambda x: x not in [10], range(page*5, page*5+5)))        # 10 cannot be read, virtual switches

            print(f"ids: {ids}")
            self.mp2.vebus.send_snapshot_request(ids)
#            time.sleep(0.1)
            for phase in range(1,4):
                try:
                    print(f"Phase {phase}")
                    ret = self.mp2.vebus.read_snapshot(ids, phase=phase)
                    print(ret)
                    if ret:
                        phase_dict[phase].update(ret)
                #    print(phase_dict)
                except Exception as ex:
                    print(ex)
                    traceback.print_exc()

        pprint.pprint(phase_dict)

#        settings_to_read = [0, 1, 2, 3, 4, 14, 64]
        
        for phase in range(1,4):
            flag0_15 = self.mp2.vebus.read_settings(0, phase=phase)
            flag0_16_text = '{0:016b}'.format(flag0_15)
            phase_dict[phase].update({f"flag0_16_text": flag0_16_text})

            for i, bit in enumerate(reversed(flag0_16_text), start=0):
                print(f"bit {i} = {'true' if bit == '1' else 'false'}")

            flag16_31 = self.mp2.vebus.read_settings(1, phase=phase)
            flag16_31_text = '{0:016b}'.format(flag16_31)
            phase_dict[phase].update({f"flag16_31_text": flag16_31_text})

            for i, bit in enumerate(reversed(flag16_31_text), start=16):
                print(f"bit {i} = {'true' if bit == '1' else 'false'}")

        settings_to_read = [2, 11, 15, 64]
        for setting_id in settings_to_read:
            print(f"setting {setting_id}")
            for phase in range(1,2):
                ret = self.mp2.vebus.read_settings(setting_id, phase=phase)
                print(f"phase {phase} setting {setting_id} = {ret}, {bin(ret)} {int(ret)}")
                # bit_string = bin(ret)[2:]  # Remove '0b' prefix
                # for i, bit in enumerate(bit_string, start=1):
                #     print(f"bit {i-1} = {'true' if bit == '1' else 'false'}")
                phase_dict[phase].update({f"setting_{setting_id}": ret})


#        soc=72
#        self.mp2.vebus.write_ram_var(vebus_constants.RAM_IDS['ChargeState'], 
#                                     vebus_constants.RAM_IDS_write.get('ChargeState', lambda x: x)(soc))


        if self.mqtt_client:
            self.mqtt_client.publish(self.config['VICTRON']['fetch_data_topic'], json.dumps(phase_dict))

# #        ret = self.mp2.vebus.set_power_3p(100,100,100)
        # print(self.mp2.vebus.set_power_phase(0,1))
        # print(self.mp2.vebus.set_power_phase(0,2))
        # print(self.mp2.vebus.set_power_phase(0,3))

      #  self.mp2.vebus.reset_device(0)

#        self.mp2.vebus.set_ess_modules(disable_feed=True, disable_charge=True, phase=1)

        pprint.pprint(phase_dict)


        print("end")
  


    def call_cmd(self, data):
        logging.info(f"got cmd: {data}")
        cmd = data.get('cmd')
        if cmd == 'reset':
            logging.info("reset mp2")
            self.mp2.vebus.reset_device(0)
        elif cmd == 'sleep':
            logging.info("sleep mp2")
            self.mp2.vebus.sleep()
        elif cmd == 'wakeup':
            logging.info("wakeup mp2")
            self.mp2.vebus.wakeup()
        elif cmd == 'fetch_data':
            logging.info("fetch data")
            self.fetch_data()
        else:
            logging.warning(f"unknown cmd {cmd}")

def on_message(mqtt_client, set_point_class, message):
    logging.debug(f"message received topic: {message.topic} {str(message.payload.decode('utf-8'))}")
    try:
        data = json.loads(str(message.payload.decode("utf-8")))

        if message.topic == set_point_class.smartmeter_topic:
            logging.debug(f"update from smartmeter: {data['power']}")
            set_point_class.update_sm_power(data['power']*-1)
        elif message.topic == set_point_class.bms1_topic:
            logging.info(f"update from bms1: soc: {data['soc']}, voltage: {data['voltage']}")
            set_point_class.update_bms_soc(data['soc'])
        elif message.topic == set_point_class.mppt_topic:
            set_point_class.update_mppt(data)
        elif message.topic == set_point_class.cmd_topic:
            set_point_class.call_cmd(data)
        elif message.topic == set_point_class.soc_min_topic:
            logging.warning(f"update soc_min: {data}")
            set_point_class.config['VICTRON']['MIN_SOC'] = str(data)
        elif message.topic == set_point_class.soc_max_topic:
            logging.warning(f"update soc_max: {data}")
            set_point_class.config['VICTRON']['MAX_SOC'] = str(data)
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
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s %(message)s', stream=sys.stdout)
    sysloghandler=logging.handlers.SysLogHandler(address='/dev/log')
    sysloghandler.setLevel(logging.WARNING)
    logging.getLogger().addHandler(sysloghandler)

    logging.warning("start update_setpoint.py")

    parser = argparse.ArgumentParser()
    parser.add_argument("--config", help="config.ini file", default="config.ini")
    parser.add_argument("--dump", help="dump option", action="store_true")
    args = parser.parse_args()
    config_file=args.config

    read_config()

    mqtt_client = mqtt.Client("UPDATE_SETPOINT")
    set_point_class=SetPoint(mqtt_client, config)

    if config['MQTT'].get('user'):
        logging.info("mqtt password given")
        mqtt_client.username_pw_set(config['MQTT']['user'], config['MQTT']['password'])

    mqtt_client.on_message = on_message

    logging.info(f"connect to mqtt server {config['MQTT']['host']}")
    mqtt_client.connect(config['MQTT']['host'], int(config['MQTT']['port']))

    topics = {
        'smartmeter_topic': config['SMARTMETER']['topic'],
        'bms1_topic': config['BMS1']['topic'],
        'mppt_topic': config['VICTRON'].get('mppt_topic'),
        'cmd_topic': config['VICTRON'].get('cmd_topic'),
        'soc_min_topic': config['VICTRON'].get('soc_min_topic'),
        'soc_max_topic': config['VICTRON'].get('soc_max_topic'),
    }

    # Subscribe to each topic
    for topic_name, topic in topics.items():
        if topic:  # Check if topic is not None
            logging.info(f"Subscribe {topic}")
            mqtt_client.subscribe(topic)
        setattr(set_point_class, topic_name, topic)

    mqtt_client.user_data_set(set_point_class)


    #client.subscribe("#")

    signal.signal(signal.SIGHUP, signal_hub_handler)

    if args.dump:
        set_point_class.fech_data()
        return None

    logging.info("start loop")
    mqtt_client.loop_forever()

if __name__ == '__main__':
    main()
