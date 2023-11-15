#!/usr/bin/python3
# use this to decode HDLC packets from a powergrid smartmeter.
# supported data sources so far:
#  'WN'     WienerNetze   ISKRAEMECO AM550 from D0 interface (infrared)
#  'KN'     KärntenNetz   ISKRAEMECO AM550 from P1 interface (RJ12)
#  'WN350'  WienerNetze   SIEMENS IM350 from D0 interface (infrared)
#
# you might need to install pycryptodome:
# pip install pycryptodome


#paste your AES-key here
#in case of WienerNetze: can be found from WienerNetze Webportal https://www.wienernetze.at/wnapp/smapp/ -> Anlagedaten

# data string of WienerNetze AM550 explained:
# 7e         start-byte, hdlc opening flag
# a0         address field?
# 67         length field?
# cf         control field?
# 02         length field?
# 23         ?
# 13         frame type
# fbf1       crc16 from byte 2-7
# e6e700     some header?
# db         some header?
# 08         length of next field
# 44556677889900aa   systemTitle
# 4f         length of next field
# 20         security byte: encryption-only
# 88887777   invocation counter
# 5540d5496ab897685e9b7e469942209b881fe280526f77c9d1dee763afb463a9bbe88449cb3fe79725875de945a405cb0f3119d3e06e3c4790130a29bc090cdf4b323cd7019d628ca255 ciphertext
# fce5       crc16 from byte 2 until end of ciphertext
# 7e         end-byte

## lets go
import binascii
import serial
import paho.mqtt.client as mqtt
import json
import configparser
#from Crypto.Cipher import AES
from Cryptodome.Cipher import AES
import argparse


##CRC-STUFF BEGIN
CRC_INIT=0xffff
POLYNOMIAL=0x1021

def byte_mirror(c):
    c=(c&0xF0)>>4|(c&0x0F)<<4
    c=(c&0xCC)>>2|(c&0x33)<<2
    c=(c&0xAA)>>1|(c&0x55)<<1
    return c

def calc_crc16(data):
    crc=CRC_INIT
    for i in range(len(data)):
        c=byte_mirror(data[i])<<8
        for j in range(8):
            if (crc^c)&0x8000: crc=(crc<<1)^POLYNOMIAL
            else: crc=crc<<1
            crc=crc%65536
            c=(c<<1)%65536
    crc=0xFFFF-crc
    return 256*byte_mirror(crc//256)+byte_mirror(crc%256)

def verify_crc16(input, skip=0, last=2, cut=0):
    lenn=len(input)
    data=input[skip:lenn-last-cut]
    goal=input[lenn-last-cut:lenn-cut]
    if   last == 0: return hex(calc_crc16(data))
    elif last == 2: return calc_crc16(data)==goal[0]*256 + goal[1]
    return False
##CRC-STUFF DONE

##DECODE-STUFF BEGIN

def decode_packet(input):  ##expects input to be bytearray.fromhex(hexstring), full packet  "7ea067..7e"
 #   if verify_crc16(input, 1, 2, 1):
    if True:
        global device
        if device=='WN350': add=2
        else: add=0
        nonce=bytes(input[14+add:22+add]+input[24+add:28+add])  #systemTitle+invocation counter
        cipher=AES.new(binascii.unhexlify(key), AES.MODE_CTR, nonce=nonce, initial_value=2)
        return cipher.decrypt(input[28+add:-3])
    else:
        return ''
##DECODE-STUFF DONE

def bytes_to_int(bytes):
    result = 0
    for b in bytes:
        result = result * 256 + b
    return result

def show_data(s):
    ret=""
    global device
    if device=='WN' or device=='WN350':
        if device=='WN350': add=18
        else: add=0
        a=bytes_to_int(s[35+add:39+add])/1000.000  #+A Wh
        b=bytes_to_int(s[40+add:44+add])/1000.000  #-A Wh
        c=bytes_to_int(s[45+add:49+add])/1000.000  #+R varh
        d=bytes_to_int(s[50+add:54+add])/1000.000  #-R varh
        e=bytes_to_int(s[55+add:59+add])           #+P W
        f=bytes_to_int(s[60+add:64+add])           #-P W
        g=bytes_to_int(s[65+add:69+add])           #+Q var
        h=bytes_to_int(s[70+add:74+add])           #-Q var
        yyyy=bytes_to_int(s[22+add:24+add])
        mm=bytes_to_int(s[24+add:25+add])
        dd=bytes_to_int(s[25+add:26+add])
        hh=bytes_to_int(s[27+add:28+add])
        mi=bytes_to_int(s[28+add:29+add])
        ss=bytes_to_int(s[29+add:30+add])
        ret="Output: %10.3fkWh, %10.3fkWh, %10.3fkvarh, %10.3fkvarh, %5dW, %5dW, %5dvar, %5dvar at %02d.%02d.%04d-%02d:%02d:%02d" %(a,b,c,d,e,f,g,h, dd,mm,yyyy,hh,mi,ss)
    elif device=='KN':
        a=bytes_to_int(s[57:61])/1000.000  #+A Wh
        b=bytes_to_int(s[62:66])/1000.000  #-A Wh
        c=bytes_to_int(s[67:71])/1000.000  #+R varh
        d=bytes_to_int(s[72:76])/1000.000  #-R varh
        e=bytes_to_int(s[77:81])           #+P W
        f=bytes_to_int(s[82:86])           #-P W
        yyyy=bytes_to_int(s[51:53])
        mm=bytes_to_int(s[53:54])
        dd=bytes_to_int(s[54:55])
        hh=bytes_to_int(s[45:46])
        mi=bytes_to_int(s[46:47])
        ss=bytes_to_int(s[47:48])
        #ret="Output: %10.3fkWh, %10.3fkWh, %10.3fkvarh, %10.3fkvarh, %5dW, %5dW at %02d.%02d.%04d-%02d:%02d:%02d" %(a,b,c,d,e,f, dd,mm,yyyy,hh,mi,ss)
        ret="%10.3f;%10.3f;%10.3f;%10.3f;%5d;%5d;%02d.%02d.%04d-%02d:%02d:%02d" %(a,b,c,d,e,f, dd,mm,yyyy,hh,mi,ss)
    else:
        ret="Device type not recognized"
    return ret



def get_data(s):
    global device
    if device=='WN' or device=='WN350':
        if device=='WN350': add=18
        else: add=0
        a=bytes_to_int(s[35+add:39+add])/1000.000  #+A Wh
        b=bytes_to_int(s[40+add:44+add])/1000.000  #-A Wh
        c=bytes_to_int(s[45+add:49+add])/1000.000  #+R varh
        d=bytes_to_int(s[50+add:54+add])/1000.000  #-R varh
        e=bytes_to_int(s[55+add:59+add])           #+P W
        f=bytes_to_int(s[60+add:64+add])           #-P W
        g=bytes_to_int(s[65+add:69+add])           #+Q var
        h=bytes_to_int(s[70+add:74+add])           #-Q var
        yyyy=bytes_to_int(s[22+add:24+add])
        mm=bytes_to_int(s[24+add:25+add])
        dd=bytes_to_int(s[25+add:26+add])
        hh=bytes_to_int(s[27+add:28+add])
        mi=bytes_to_int(s[28+add:29+add])
        ss=bytes_to_int(s[29+add:30+add])
    elif device=='KN':
        a=bytes_to_int(s[57:61])/1000.000  #+A Wh
        b=bytes_to_int(s[62:66])/1000.000  #-A Wh
        c=bytes_to_int(s[67:71])/1000.000  #+R varh
        d=bytes_to_int(s[72:76])/1000.000  #-R varh
        e=bytes_to_int(s[77:81])           #+P W
        f=bytes_to_int(s[82:86])           #-P W
        yyyy=bytes_to_int(s[51:53])
        mm=bytes_to_int(s[53:54])
        dd=bytes_to_int(s[54:55])
        hh=bytes_to_int(s[45:46])
        mi=bytes_to_int(s[46:47])
        ss=bytes_to_int(s[47:48])
        #ret="Output: %10.3fkWh, %10.3fkWh, %10.3fkvarh, %10.3fkvarh, %5dW, %5dW at %02d.%02d.%04d-%02d:%02d:%02d" %(a,b,c,d,e,f, dd,mm,yyyy,hh,mi,ss)
        ret="%10.3f;%10.3f;%10.3f;%10.3f;%5d;%5d;%02d.%02d.%04d-%02d:%02d:%02d" %(a,b,c,d,e,f, dd,mm,yyyy,hh,mi,ss)
    else:
        return None 
    return (a,b,e,f)

parser = argparse.ArgumentParser()
parser.add_argument("--config", help="config.ini file", default="config.ini")
args = parser.parse_args()

config = configparser.ConfigParser()
config.read(args.config)
key=config['SMARTMETER']['aes_key']
device=config['SMARTMETER']['country_code']

client = mqtt.Client("smartmeter")

if config['MQTT'].get('user'):
    client.username_pw_set(config['MQTT']['user'], config['MQTT']['password'])
client.connect(config['MQTT']['host'], int(config['MQTT']['port']))
client.loop_start()

while 1:
    print("opening serial interface")
    try:
        ser=serial.Serial(config['SMARTMETER']['serial_port'], baudrate=int(config['SMARTMETER']['serial_baudrate']), timeout=1)
    #ser=serial.Serial("/dev/ttyACM0",baudrate=115200)
#        outfile=open("out.txt", mode="a")

        count=0
        while(1):

            junk1=ser.read_until(expected=b'\x7e')
            junk2=ser.read_until(expected=b'\xa0')
        
            data=ser.read(119)
        
            data2=b'\x7e\xa0'+data+b'\x7e'
            dec=decode_packet(data2)
            s=show_data(dec)
            print(s)
  
            (sin, sout, pin, pout)=get_data(dec)
            data={
                "power_in": pin,
                "power_out": pout,
                "power": pin-pout,
                "power_unit": "W",
                "total_in": sin,
                "total_out": sout,
                "total_unit": "KWh",
            }
            print(data)
            rc=client.publish(config['SMARTMETER']['TOPIC'], json.dumps(data))
            print(rc)
            dspl = {"title": "Smartmeter",
                    "color": 24555,
                    "main": {"unit": "W",
                        "PwrSM": data["power"]
                        },
                    "stand": {
                        "unit": "KWh",
                        "In": "{:.1f}".format(data["sum_in"]),
                        "Out": "{:.1f}".format(data["sum_out"])
                        }
                    }
            client.publish("display", json.dumps(dspl))

    except Exception as ex:
        print(ex)
        import time
        time.sleep(1)
    finally:
        if ser:
            ser.close()
