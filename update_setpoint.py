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
import logging.config
import sys
import signal
import datetime
import pprint
import vebus_constants
from vebus import VEBus

log = logging.getLogger(__name__)

MAX_VICTRON_RAMP=400

# https://github.com/yvesf/ve-ctrl-tool

class SetPoint:
    def __init__(self, mqtt_client, config):
        self.vebus = VEBus(port=config['VICTRON']['serial_port'], log='vebus')
        self.connect()
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
        self.current_phase=1
        self.phases=3
        self.phase_dict={1:{}, 2:{}, 3:{}}
        

    def update_bms_soc(self, bms_soc):
        self.bms_soc=bms_soc
        self.last_bms_soc_data=time.time()

    def update_mppt(self, data):
        self.mppt_power=data.get('PPV',0)
        self.last_mppt_power=time.time()
        log.info(f"mppt power: {self.mppt_power}")

    def get_max_charge(self):
        return float(self.config['VICTRON']['MAX_CHARGE'])

    def get_max_invert(self):
        max_invert=float(self.config['VICTRON']['MAX_INVERT'])
        min_soc=float(self.config['VICTRON']['MIN_SOC'])

        max_invert2=math.tanh(((self.bms_soc-min_soc) / 10))*max_invert

        if self.last_mppt_power and time.time()-self.last_mppt_power < 20:  # we have current value
            if self.mppt_power-160 > max_invert2:
                log.debug(f"increate max_invert2 to {max_invert2} because of mppt power {self.mppt_power}")
                max_invert2=self.mppt_power - 160

        return max(max_invert2, 300)       # mindesten 300 Watt Leistung


    def set_mp2_setpoint(self, setpoint, standby=False):
        ret = True
        if standby:
            if not self.battery_empty_ts:
                self.battery_empty_ts=time.time()

            if self.config.getboolean('VICTRON','sleep_enabled', fallback=False):
                if self.battery_empty_ts and time.time()-self.battery_empty_ts > self.config.getint('VICTRON','SLEEP_TIMEOUT', fallback=3600):
                    log.warning("battery empty for 5 minutes, go to standby")
                    self.vebus.sleep()

                    self.mp2_standby=True
                    self.battery_empty_ts=None
            
        else:
            if self.mp2_standby:
                log.warning("wakeup mp2 from standby")
                self.vebus.wakeup()
                self.mp2_standby=False
            
            if self.mp2_device_state_name=='off':
                log.warning("mp2 is off, wakeup")
                self.vebus.wakeup()

#            ret=self.vebus.set_power(int(setpoint))
#            ret=self.vebus.set_power_phase(int(setpoint), phase=2)
#            ret=self.vebus.set_power_phase(int(setpoint/3), phase=1)
#            ret=self.vebus.set_power_phase(int(setpoint/3), phase=2)
#            ret=self.vebus.set_power_phase(int(setpoint/3), phase=3)
            ret=self.vebus.set_power_phase(int(setpoint/3), phase=self.current_phase)
                
#            ret=self.vebus.set_power_3p(int(setpoint/3),int(setpoint/3),int(setpoint/3))

        if setpoint>0:
            self.mp2_charge=True
            self.mp2_invert=False
        elif setpoint<0:
            self.mp2_charge=False
            self.mp2_invert=True
        else:
            self.mp2_charge=False
            self.mp2_invert=False

        return ret

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
        # if not self.mp2:
        #     log.error("no mp2")
        #     return
        data=self.get_data()

        self.mp2_device_state_name=data.get('device_state_name',None)
        victron_ok=False

        if not self.last_bms_soc_data or time.time()-self.last_bms_soc_data > 60:  # last bms data older than 5 minutes
            self.bms_soc=data.get('soc',0)
            log.debug(f"no bms data, use mp2 data {self.bms_soc}")

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

        log.info(f"mp2_power={self.mp2_power}, old: {self.mp2_power_old} sum: {sm_power}")
        
        if self.mp2_power>self.get_max_charge():
            self.mp2_power=self.get_max_charge()
        if self.mp2_power< -1* self.get_max_invert():
            self.mp2_power=-1* self.get_max_invert()

        if self.mp2_standby and self.mp2_power>0 and sm_power < -50:
            log.info("mp2 is in standby, but power is less than 100W, keep standby")
            self.mp2_power=0

        data['mp2_power_request']=self.mp2_power
        if data.get('inv_p',0) >=0:
            data['inv_p_in']=data.get('inv_p',0)
            data['inv_p_out']=0
        else:
            data['inv_p_out']=data.get('inv_p',0)*-1
            data['inv_p_in']=0

        bat_u=data.get('bat_u',0)
        if 'bat_u' in data and 'bat_i' in data and 'mains_i' in data and 'inv_i' in data:
            victron_ok=True
        else:
            log.warning(f"got incomplete data from victron {data}")


        # rc=self.mqtt_client.publish(self.config['VICTRON']['topic'], json.dumps(data))
        # log.debug(rc)

#        batu_hyst=52.3 - 0.5 if self.mp2_invert else 0
#        if self.bms_soc < 21 and data.get('bat_u',0)>batu_hyst:
#            log.info(f"soc {self.bms_soc} too low but battery full {data.get('bat_u')}")
#            self.bms_soc=21
        set_power_ok=False
        log.info(f"mp2_power={self.mp2_power}, soc: {self.bms_soc}, bat_u: {bat_u}")
        
        if self.mp2_power>0:
            max_soc_hyst=float(self.config['VICTRON']['MAX_SOC']) + (float(self.config['VICTRON']['SOC_HYSTERESIS']) if self.mp2_charge else 0)
            if self.bms_soc < max_soc_hyst:
                log.info(f"wakeup and set power {self.mp2_power}")
                set_power_ok=self.set_mp2_setpoint(int(self.mp2_power), standby=False)
            else:
                log.info(f"battery full not {self.bms_soc} < {max_soc_hyst}")
                set_power_ok=self.set_mp2_setpoint(0, standby=False)
        else:
            min_soc_hyst = float(self.config['VICTRON']['MIN_SOC']) - (float(self.config['VICTRON']['SOC_HYSTERESIS']) if self.mp2_invert else 0)
            if self.bms_soc > min_soc_hyst :
                log.info(f"set power {self.mp2_power}")

                set_power_ok=self.set_mp2_setpoint(int(self.mp2_power))
            else:
                log.info(f"battery empty not {self.bms_soc} > {min_soc_hyst}")
                set_power_ok=self.set_mp2_setpoint(0, True)
#                self.mp2_power=None

        if not set_power_ok:
            log.warning("unable to set power")
            victron_ok=False


        
        data=self.get_data(self.current_phase)
        data['setpoint']=self.mp2_power 
        self.phase_dict[self.current_phase]=data

        # publish phase data
        rc=self.mqtt_client.publish(f"{self.config['VICTRON']['topic']}/{self.current_phase}", json.dumps(data))

        # publish accumulated data

        accumulated_data={}
        for key in self.phase_dict[1].keys():
            value = self.phase_dict[1].get(key)
            if isinstance(value, (int, float)) and key in ('IBat', 'InverterPower1', 'InverterPower1', 'OutputPower', 
                                                           'bat_i', 'bat_p', 'inv_i', 'inv_p', 'inv_p_calc', 'mains_i', 'mains_p_calc', 
                                                           'out_p', 'own_p_calc'):
                accumulated_data[key]=sum([self.phase_dict[phase].get(key,0) for phase in range(1,len(self.phase_dict)+1)])
            else:
                accumulated_data[key]=value

        print("accumulated data")
        pprint.pprint(accumulated_data)

        rc=self.mqtt_client.publish(self.config['VICTRON']['topic'], json.dumps(accumulated_data))

        self.current_phase = self.current_phase + 1 if self.current_phase < self.phases else 1

        try:
            self.custom_update(data)
        except Exception as ex:
            log.warning(f"unable to call custom code, got {ex}", exc_info=True) 

        self.counter+=1

        if victron_ok:
            if self.counter > 10:
                self.touch_file()
                self.counter=0
        else:
            log.warning("victron not ok")

    def touch_file(self):
        f = open("watchdog.txt", "w")
        f.write(f"Watchdog on {datetime.datetime.now()}")
        f.close()
        log.debug("touch watchdog.txt")

    def get_ram_var_infos(self):
        (soc_sc, soc_offset) = self.vebus.read_ram_var_info(vebus_constants.RAM_IDS['ChargeState'])
        print(f"soc_sc: {soc_sc}, soc_offset: {soc_offset}")

        (sc, offset) = self.vebus.read_ram_var_info(vebus_constants.RAM_IDS['UBat'])
        print(f"ubat: soc_sc: {sc}, soc_offset: {offset}")

        (sc, offset) = self.vebus.read_ram_var_info(vebus_constants.RAM_IDS['UMainsRMS'])
        print(f"UMainsRMS: sc: {sc}, offset: {offset}")



    def fech_data(self):
#        self.mp2.update()
#        data=self.mp2.data
#        print(data)


#        infos=self.get_ram_var_infos()
#        return None

        phase_dict={1:{}, 2:{}, 3:{}}

        for phase in range (1,4):
            print(f"Phase {phase}")
            ac_info = self.vebus.get_ac_info(phase)
            print(ac_info)
            phase_dict[phase].update({"ac_info": ac_info })

        for page in range(0,4):
            ids = list(filter(lambda x: x not in [10], range(page*5, page*5+5)))        # 10 cannot be read, virtual switches

            print(f"ids: {ids}")
            self.vebus.send_snapshot_request(ids)
#            time.sleep(0.1)
            for phase in range(1,4):
                try:
                    print(f"Phase {phase}")
                    ret = self.vebus.read_snapshot(ids, phase=phase)
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
            flag0_15 = self.vebus.read_settings(0, phase=phase)
            flag0_16_text = '{0:016b}'.format(flag0_15)
            phase_dict[phase].update({f"flag0_16_text": flag0_16_text})

            for i, bit in enumerate(reversed(flag0_16_text), start=0):
                print(f"bit {i} = {'true' if bit == '1' else 'false'}")

            flag16_31 = self.vebus.read_settings(1, phase=phase)
            flag16_31_text = '{0:016b}'.format(flag16_31)
            phase_dict[phase].update({f"flag16_31_text": flag16_31_text})

            for i, bit in enumerate(reversed(flag16_31_text), start=16):
                print(f"bit {i} = {'true' if bit == '1' else 'false'}")

        settings_to_read = [2, 11, 15, 64]
        for setting_id in settings_to_read:
            print(f"setting {setting_id}")
            for phase in range(1,2):
                ret = self.vebus.read_settings(setting_id, phase=phase)
                print(f"phase {phase} setting {setting_id} = {ret}, {bin(ret)} {int(ret)}")
                # bit_string = bin(ret)[2:]  # Remove '0b' prefix
                # for i, bit in enumerate(bit_string, start=1):
                #     print(f"bit {i-1} = {'true' if bit == '1' else 'false'}")
                phase_dict[phase].update({f"setting_{setting_id}": ret})


#        soc=72
#        self.vebus.write_ram_var(vebus_constants.RAM_IDS['ChargeState'], 
#                                     vebus_constants.RAM_IDS_write.get('ChargeState', lambda x: x)(soc))


        if self.mqtt_client:
            self.mqtt_client.publish(self.config['VICTRON']['fetch_data_topic'], json.dumps(phase_dict))

# #        ret = self.vebus.set_power_3p(100,100,100)
        # print(self.vebus.set_power_phase(0,1))
        # print(self.vebus.set_power_phase(0,2))
        # print(self.vebus.set_power_phase(0,3))

      #  self.vebus.reset_device(0)

#        self.vebus.set_ess_modules(disable_feed=True, disable_charge=True, phase=1)

        pprint.pprint(phase_dict)


        print("end")
  

    def get_data(self, phase=1):
        start_time=time.perf_counter()

        ac_dict={}
        snapshot_dict={}

        snapshot_ids = [vebus_constants.RAM_IDS['InverterPower2'], 
                        vebus_constants.RAM_IDS['OutputPower'],
                        vebus_constants.RAM_IDS['UBat'],
                        vebus_constants.RAM_IDS['IBat'],
                        vebus_constants.RAM_IDS['ChargeState'],
                        vebus_constants.RAM_IDS['InverterPower1']]  # up to 6x
        
        self.vebus.send_snapshot_request(snapshot_ids)  # trigger snapshot

        ac_dict = self.vebus.get_ac_info(phase)

        ac_info_time=time.perf_counter()

        snapshot_data = self.vebus.read_snapshot(snapshot_ids, phase=phase)
        if snapshot_data:
            snapshot_dict.update(snapshot_data)

        # snapshot_ids = [vebus_constants.RAM_IDS[''], 
        #                 vebus_constants.RAM_IDS[''],
        #                 vebus_constants.RAM_IDS[''],
        #                 vebus_constants.RAM_IDS[''],
        #                 vebus_constants.RAM_IDS[''],
        #                 vebus_constants.RAM_IDS['']]  # up to 6x
        # self.vebus.send_snapshot_request(snapshot_ids)  # trigger snapshot            
        # snapshot_data = self.vebus.read_snapshot(snapshot_ids, phase=phase)
        # if snapshot_data:
        #     snapshot_dict.update(snapshot_data)


        # for compatibiliy with old code
        snapshot_dict['bat_u']=snapshot_dict.get('UBat',0)
        snapshot_dict['bat_i']=snapshot_dict.get('IBat',0)
        snapshot_dict['bat_p']=round(snapshot_dict.get('UBat',0)*snapshot_dict.get('IBat',0))
        snapshot_dict['inv_p']=-1*snapshot_dict.get('InverterPower2',0)
        snapshot_dict['out_p']=snapshot_dict.get('OutputPower',0)
        snapshot_dict['soc']=snapshot_dict.get('ChargeState',0)

        # snapshot_ids = [1,2,3,4,5,6]  # up to 6x
        # self.vebus.send_snapshot_request(snapshot_ids)  # trigger snapshot
        # snapshot_data = self.vebus.read_snapshot(snapshot_ids, phase=phase)
        # if snapshot_data:
        #     snapshot_dict.update(snapshot_data)

        # snapshot_ids = [7,8,9,11,12,13]  # up to 6x
        # self.vebus.send_snapshot_request(snapshot_ids)  # trigger snapshot
        # snapshot_data = self.vebus.read_snapshot(snapshot_ids, phase=phase)
        # if snapshot_data:
        #     snapshot_dict.update(snapshot_data)

        # snapshot_ids = [14,15,16]  # up to 6x
        # self.vebus.send_snapshot_request(snapshot_ids)  # trigger snapshot
        # snapshot_data = self.vebus.read_snapshot(snapshot_ids, phase=phase)
        # if snapshot_data:
        #     snapshot_dict.update(snapshot_data)


        # part3 = self.vebus.get_led()  # read led infos and append to data dictionary
        #     if part3:
        #             data = {}
        #             data.update(part1)
        #             data.update(part2)
        #             data.update(part3)
        #             led = data.get('led_light', 0) + data.get('led_blink', 0)
        #             state = data.get('device_state_id', None)
        #             if state == 2:
        #                 data['state'] = 'sleep'
        #             elif led & 0x40:
        #                 data['state'] = 'low_bat'
        #             elif led & 0x80:
        #                 data['state'] = 'temperature'
        #             elif led & 0x20:
        #                 data['state'] = 'overload'
        #             elif state == 8 or state == 9:
        #                 data['state'] = 'on'
        #             elif state == 4:
        #                 data['state'] = 'wait'
        #             else:
        #                 data['state'] = '?{}?0x{:02X}?'.format(state, led)

        #             self.data = data
#                    self.data_timeout = time.perf_counter() + self.timeout  # reset data timeout with valid rx


        data={}
        data.update(ac_dict)
        data.update(snapshot_dict)

        end_time=time.perf_counter()
        log.info(f"get_data took {end_time-start_time} seconds")
        log.info(f"ac_info took {ac_info_time-start_time} seconds")
        log.info(f"snapshot took {end_time-ac_info_time} seconds")

        pprint.pprint(data)

        return data
    

    def connect(self):
        version = self.vebus.get_version()  # hide errors while scanning
        if version:
            self.data = {'mk2_version': version}  # init dictionary
            time.sleep(0.1)
            if self.vebus.init_address():
                time.sleep(0.1)
                if self.vebus.scan_ess_assistant():
                    log.info("ess assistant setpoint ramid={}".format(self.vebus.ess_setpoint_ram_id))
                    self.data['state'] = 'init'
                    self.online = True


    def call_cmd(self, data):
        log.info(f"got cmd: {data}")
        cmd = data.get('cmd')
        if cmd == 'reset':
            log.info("reset mp2")
            self.vebus.reset_device(0)
        elif cmd == 'sleep':
            log.info("sleep mp2")
            self.vebus.sleep()
        elif cmd == 'wakeup':
            log.info("wakeup mp2")
            self.vebus.wakeup()
        elif cmd == 'fetch_data':
            log.info("fetch data")
            self.fetch_data()
        else:
            log.warning(f"unknown cmd {cmd}")

def on_message(mqtt_client, set_point_class, message):
    log.debug(f"message received topic: {message.topic} {str(message.payload.decode('utf-8'))}")
    try:
        data = json.loads(str(message.payload.decode("utf-8")))

        if message.topic == set_point_class.smartmeter_topic:
            log.debug(f"update from smartmeter: {data['power']}")
            set_point_class.update_sm_power(data['power']*-1)
        elif message.topic == set_point_class.bms1_topic:
            log.info(f"update from bms1: soc: {data['soc']}, voltage: {data['voltage']}")
            set_point_class.update_bms_soc(data['soc'])
        elif message.topic == set_point_class.mppt_topic:
            set_point_class.update_mppt(data)
        elif message.topic == set_point_class.cmd_topic:
            set_point_class.call_cmd(data)
        elif message.topic == set_point_class.soc_min_topic:
            log.warning(f"update soc_min: {data}")
            set_point_class.config['VICTRON']['MIN_SOC'] = str(data)
        elif message.topic == set_point_class.soc_max_topic:
            log.warning(f"update soc_max: {data}")
            set_point_class.config['VICTRON']['MAX_SOC'] = str(data)
        else:
            log.info(f"unknown topic {message.topic}")
            log.info(f"not {set_point_class.config['SMARTMETER']['topic']}")

    except Exception as ex:
        log.error(ex, exc_info=True)

def read_config():
    global config
    global config_file
    if not config:
        config = configparser.ConfigParser()
    config.read(config_file)

def signal_hub_handler(signal, frame):
    log.warning("got hub signal")
    read_config()



# global variables
config=None
config_file=None

# main program
def main():
    global config_file

    try:
        logging.config.fileConfig('logging.ini')
    except Exception as ex:
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s %(message)s', stream=sys.stdout)
        sysloghandler=logging.handlers.SysLogHandler(address='/dev/log')
        sysloghandler.setLevel(logging.WARNING)
        logging.getLogger().addHandler(sysloghandler)

    log.warning(f"start update_setpoint.py {datetime.datetime.now()}")

    parser = argparse.ArgumentParser()
    parser.add_argument("--config", help="config.ini file", default="config.ini")
    parser.add_argument("--dump", help="dump option", action="store_true")
    args = parser.parse_args()
    config_file=args.config

    read_config()

    mqtt_client = mqtt.Client("UPDATE_SETPOINT")
    set_point_class=SetPoint(mqtt_client, config)

    if config['MQTT'].get('user'):
        log.info("mqtt password given")
        mqtt_client.username_pw_set(config['MQTT']['user'], config['MQTT']['password'])

    mqtt_client.on_message = on_message

    log.info(f"connect to mqtt server {config['MQTT']['host']}")
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
            log.info(f"Subscribe {topic}")
            mqtt_client.subscribe(topic)
        setattr(set_point_class, topic_name, topic)

    mqtt_client.user_data_set(set_point_class)


    #client.subscribe("#")

    signal.signal(signal.SIGHUP, signal_hub_handler)

    if args.dump:
        set_point_class.fech_data()
        return None

    log.info("start loop")
    mqtt_client.loop_forever()

if __name__ == '__main__':
    main()
