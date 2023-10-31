import struct
import serial
import paho.mqtt.client as mqtt
import json
import time
import configparser
import argparse


def get_frame_checksum(frame: bytes):
   sum = 0
   for byte in frame:
       sum += byte
   sum = ~sum
   sum %= 0x10000
   sum += 1
   return sum


def read_and_send():

    parser = argparse.ArgumentParser()
    parser.add_argument("--config", help="config.ini file", default="config.ini")
    args = parser.parse_args()

    config = configparser.ConfigParser()
    config.read(args.config)

    try:
        ser=serial.Serial(config['BMS1']['serial_port'], baudrate=int(config['BMS1']['serial_baudrate']), timeout=1)

        client = mqtt.Client("BMS1")

        if config['MQTT'].get('user'):
            client.username_pw_set(config['MQTT']['user'], config['MQTT']['password'])
        client.connect(config['MQTT']['host'], int(config['MQTT']['port']))

        bms_data={}

        seplos_cmd='~20004642E00201FD36\r\n'.encode()
        print(seplos_cmd)
        ser.write(seplos_cmd)
        print("waiting for answer")
        #raw_frame=ser.readline()
        raw_frame=ser.read_until(expected='\r')
        print(raw_frame)
        frame_data = raw_frame[1:len(raw_frame) - 5]
        frame_chksum = raw_frame[len(raw_frame) - 5:-1]

        got_frame_checksum=get_frame_checksum(frame_data)
        assert got_frame_checksum == int(frame_chksum, 16)


        fmt=">2s2sHHI"
        ver, adr, cid1, cid2, infolength = struct.unpack(fmt, frame_data[:struct.calcsize(fmt)])
        print(f"ver {ver}, adr {adr}, cid1 {cid1}, cid2 {cid2}, infolength {infolength}")
        infolength1=(infolength & 0xFFF0) >> 4
        print(infolength1)
        info=frame_data[struct.calcsize(fmt):]

        print(info)
        info=bytearray.fromhex(info.decode())
        print(info)
        fmt=">xxB"
        (number_of_cells,) = struct.unpack(fmt, info[:3])

        start=3
        
        cell_low=0xFFFF
        cell_high=0
        for i in range(0, number_of_cells):
            (voltage,) = struct.unpack(">H", info[start+i*2:start+2+i*2])
            voltage=voltage/1000.0
            print(f"cell{i}: {voltage}")
            bms_data[f"cell{i+1}_voltage"]=voltage
            cell_low=min(cell_low, voltage)
            cell_high=max(cell_high, voltage)
        
        bms_data['cell_low']=cell_low
        bms_data['cell_high']=cell_high
        bms_data['cell_diff']=round(cell_high-cell_low, 4)
        
        start+=number_of_cells*2
        start+=1
        temp_list=[]
        for i in range(0, 6):
            (temp,) = struct.unpack(">H", info[start+i*2:start+2+i*2])
            temp=(temp-2731)/10.0
            print(f"temp{i}: {temp}")
            temp_list.append(temp)

        bms_data['cellblock1_temp']=temp_list[0]
        bms_data['cellblock2_temp']=temp_list[1]
        bms_data['cellblock3_temp']=temp_list[2]
        bms_data['cellblock4_temp']=temp_list[3]
        bms_data['environment_temp']=temp_list[4]
        bms_data['power_temp']=temp_list[5]


        start+=6*2
        (current, voltage, capacity_residual, capacity_total, soc, rated_capacity, number_of_cycle, soh, port_voltage) = struct.unpack(">HHHxHHHHHH", info[start:start+19])
        current/=100
        voltage/=100
        capacity_residual/=100
        capacity_total/=100
        rated_capacity/=100
        soh/=10
        soc/=10
        port_voltage/=100
        print(f"current: {current}, voltage: {voltage}, capacity_residual: {capacity_residual}, capacity_total: {capacity_total}, soc: {soc}, rated_capacity: {rated_capacity}")
        print(f"number_of_cycle {number_of_cycle}, soh {soh} port_voltage {port_voltage}")

        print(f"number_of_cells: {number_of_cells}")

        print(info[:5])

        bms_data['current']=current
        bms_data['voltage']=voltage
        bms_data['capacity_residual']=capacity_residual
        bms_data['capacity_total']=capacity_total
        bms_data['soc']=soc
        bms_data['rated_capacity']=rated_capacity
        bms_data['number_of_cycle']=number_of_cycle
        bms_data['soh']=soh
        bms_data['port_voltage']=port_voltage

        print(json.dumps(bms_data))
        (rc,mqttid) = client.publish(config['BMS1']['topic'], json.dumps(bms_data))
        print(f"Publish RC: {rc}")

    except Exception as ex:
        print(ex)
        time.sleep(10)
    finally:
        if ser:
            ser.close()
        if client:
            client.disconnect()


if __name__ == '__main__':
    while True:
        read_and_send()
        time.sleep(10)
