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


def     get_chk_sum(data):
    sum = 0
    for byte in data:
        sum += byte
    sum = ~sum
    sum &= 0xFFFF
    sum += 1
    return sum

def read_and_send(shelf):

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




        seplos_get_protocol_version="~2001464F0000FD99$"
        # ~ 
        # 20 Protocol Version 2.0
        # 01 Device Address 01
        # 46 4F LiFePO4 BMS, 4FAcquisition of the communication protocol version number
        # 00 00 length
        # FD 99 Checksum
        # $ End of Frame
        seplos_get_manufacturer="~200246510000FDAC\n"
        seplos_get_telemetry_data="~20014642E00201FD35$"
        seplos_get_remote_communication_data="~20014644E00201FD33$"
        # x=b'\x7E\x32\x30\x30\x32\x34\x36\x34\x32\x45\x30\x30\x32\x30\x32\x46\x44\x33\x33\x0D'
        # y=b'\x7E\x32\x30\x30\x32\x34\x36\x34\x32\x45\x30\x30\x32\x30\x32'

  
        seplos_get_data=f"200{shelf}4642E0020{shelf}".encode()
        chksum = get_chk_sum(seplos_get_data)
        package = ("~" + seplos_get_data.decode() + "{:04X}".format(chksum) + "\r").encode()
        # print(package)
        # cs=""
        # for b in package:
        #     cs+=hex(b)+","
        # print(cs)


        


   #     seplos_cmd='~20004642E00201FD36\r\n'.encode()
     #   seplos_cmd=seplos_get_manufacturer.encode()
        seplos_cmd=package
        print(seplos_cmd)
        ser.write(seplos_cmd)
        print("waiting for answer")
        #raw_frame=ser.readline()
#        raw_frame=ser.read_until(expected='\r')
        raw_frame=ser.read_until(expected='$')
        print(raw_frame)
        frame_data = raw_frame[1:len(raw_frame) - 5]
        frame_chksum = raw_frame[len(raw_frame) - 5:-1]

        got_frame_checksum=get_frame_checksum(frame_data)
        assert got_frame_checksum == int(frame_chksum, 16)


        fmt=">2s2sHHI"
        ver, adr, cid1, cid2, infolength = struct.unpack(fmt, frame_data[:struct.calcsize(fmt)])
        print(f"ver {ver}, adr {adr}, cid1 0x{cid1:02x}, cid2 0x{cid2:02x}, infolength 0x{infolength:02x}")
        infolength1=(infolength & 0xFFF0) >> 4
        print(infolength1)
        print(f"infolength1 {infolength1}")
        print(f"start of data {struct.calcsize(fmt)}")
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
        topic=config['BMS1']['topic']
        if shelf>1:
            topic=topic+"/"+str(shelf)
        (rc,mqttid) = client.publish(topic, json.dumps(bms_data))
        print(f"Publish to {topic} RC: {rc}")

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
        for shelf in range(1, 4):
            read_and_send(shelf)
    #    time.sleep(10)
