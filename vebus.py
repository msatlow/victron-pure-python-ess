import logging
import struct
import time

import serial
import vebus_constants

"""
Victron Energy MK3 Bus Interface

Functions to control a Multiplus-II in ESS Mode 3 

Based on: Technical-Information-Interfacing-with-VE-Bus-products-MK2-Protocol-3-14.pdf and listening to the
communication between Venus OS and MK3 at the internal FTDI TXD/RXD lines.

Frame: 

<Length> 0xFF <Command> <Data 0 > ... <Data n-1 > <Checksum>

number of bytes, excluding the length and checksum, MSB of <Length> is a 1, then this frame has LED status appended
checksum is one byte


23.10.2022 Martin Steppuhn
27.11.2022 Martin Steppuhn  receive_frame() with quick and dirty start search
22.01.2023 Martin Steppuhn  scan for ess assistant (previous hardcoded setpoint at ramid 131)    
"""


class VEBus:
    def __init__(self, port, log='vebus'):
        self.port = port
        self.ess_setpoint_ram_id = None  # RAM-ID for ESS Assistant  MP2 3000 = 131
        self.log = logging.getLogger(log)
        self.serial = None
        self.open_port()

    def open_port(self):
        try:
            self.serial = serial.Serial(self.port, 2400, timeout=0)
        except Exception as e:
            self.serial = None
            self.log.error("open_port: {}".format(e))

    def get_version(self):
        """
        Read versionnumber (MK2). Also used to check connection.

        007.169 TX: 02 FF 56 A9                     V|
        007.211 RX: 07 FF 56 24 DB 11 00 42 52      V| 24 DB 11 00 42         VERSION version=1170212 mode=B

        Firmware laut VE Configure: 2629492

        :return: Versionnumber or None
        """

        if self.serial is None:
            self.open_port()  # open port

        try:
            self.send_frame('V', [])
            rx = self.receive_frame(b'\x07\xFF', timeout=0.5)
            cmd, mk2_version = struct.unpack("<BI", rx[2:7])
            self.log.info("mk2_version={}".format(mk2_version))
            return mk2_version
        except IOError:
            self.serial = None
            self.log.error("serial port failed")
        except Exception as e:
            return None

    def init_address(self, addr=0x00):
        """
        Init device address. With a single Multiplus on the bus the Address is 0x00

        011.883 TX: 04 FF 41 01 00 BB          A| 01 00          Device address: action=1 device=0
        011.925 RX: 04 FF 41 01 00 BB          A| 01 00          Device address: action=1 device=0

        :return: True/False
        """
        if self.serial is None:
            self.open_port()  # open port

        try:
            self.send_frame('A', [0x01, addr])
            rx = self.receive_frame(b'\x04\xFF\x41')
            if rx[4] == addr:  # check if correct answer and address
                self.log.info("init_address {} successful".format(addr))
                return True
            else:
                raise Exception("init_address failed")
        except IOError:
            self.serial = None
            self.log.error("serial port failed")
        except Exception as e:
            self.log.error("get_version: {}".format(e))
        return False

    def get_led(self):
        """
        Get LED status

        005.163 TX: 02 FF 4C B3                     L |                                                LED request
        005.245 RX: 08 FF 4C 01 0C 00 00 80 00 20   L | 01 0C 00 00 80 00                              LED ON:Mains BLINK:Bulk Float

        :return: {'led_light': 0, 'led_blink': 0} or None
        """
        if self.serial is None:
            self.open_port()  # open port

        try:
            self.send_frame('L', [])
            rx = self.receive_frame(b'\x08\xFF\x4C', timeout=0.5)
            led_light, led_blink = struct.unpack("<BB", rx[3:5])  # high=blink   low = light

            led_info = self.make_led_names(led_light | led_blink)

            self.log.info("led_light=0x{:02X} led_blink=0x{:02X}".format(led_light, led_blink))
            return {'led_light': led_light, 'led_blink': led_blink, 'led_info': led_info}
        except IOError:
            self.serial = None
            self.log.error("serial port failed")
        except Exception as e:
            self.log.error("get_led: {}".format(e))
            return None

    def make_led_names(self, bitmask):
        led_names = ["mains", "absorption", "bulk", "float", "inverter", "overload", "low_bat", "temperature"]
        l = []
        for i in range(len(led_names)):  # number of bits
            if bitmask & (1 << i):
                l.append(led_names[i])
        return l

    def get_ac_info(self, phase=1):
        """
        Get AC Info

        Info: VenusOS combines Snapshot request und get AC Info

        009.261 TX: 06 FF 46 06 0E 10 0F 82 03 FF 46 01 B7              F | 06 0E 10 0F    Info Request=6 RAM snapshot: Inverter Power (14), Output power, Inverter Power (15)
                  : 03 FF 46 01 B7                                      F | 01             Info Request=1 AC L1 info
        009.374 RX: 0F 20 01 01 01 09 08 EC 5A 5F FF EC 5A 08 00 C3 08  !!! AC !!! {'bf_factor': 1, 'inverter_factor': 1, 'state': 'StateCharge', 'phase_info': 8, 'mains_voltage': 23276, 'mains_current': 65375, 'inverter_voltage': 23276, 'inverter_current': 8, 'mains_period': 195}

        return: Dictionary or None
        """
        if self.serial is None:
            self.open_port()  # open port

        try:
            self.send_frame('F', [phase])
            rx = self.receive_generic_frame(0x20)
            
            logging.info(self.format_hex(rx))

            bf_factor, inv_factor, device_state_id, phase_info, mains_u, mains_i, inv_u, inv_i, mains_period = struct.unpack(
#                "<BBxBBhhhhB", rx)
                "<BBxBBhhhhB", rx[2:16])

            r = {'device_state_id': device_state_id,
                'device_state_name': vebus_constants.MULTI_STATE_invers.get(device_state_id, f"unknown_{device_state_id}"),
                'phase_info': phase_info,
                'phase_info_name': vebus_constants.PHASE_INFO_invers.get(phase_info, f"unknown_{phase_info}"),
                'mains_period': mains_period,
                'mains_u': round(mains_u / 100, 2),
                'mains_i': round(mains_i / 100, 2),
                'mains_p_calc': round(mains_u / 100 * mains_i / 100),
                'inv_u': round(inv_u / 100, 2),
                'inv_i': round(inv_i / 100, 2),
                'inv_p_calc': round(inv_u / 100 * inv_i / 100),
                'bf_factor': bf_factor,
                'inv_factor': inv_factor,
            }
            r['own_p_calc'] = round(r['mains_p_calc']-r['inv_p_calc'])
            
            self.log.info(r)
            return r
        except IOError:
            self.serial = None
            self.log.error("serial port failed")
        except Exception as e:
            self.log.error("get_ac_info: {}".format(e), exc_info=True)
            return None

    def send_snapshot_request_old(self):
        """
        Trigger a snapshot for values. Could be combined with a other request. NO RESPONSE !

        017.127 TX: 06 FF 46 06 0E 10 0F 82 05 FF 59 30 86 00 ED     F | 06 0E 10 0F        Info Request=6 RAM snapshot: Inverter Power (14), Output power, Inverter Power (15)
                  : 05 FF 59 30 86 00 ED                             Y | 30 86 00           0x30/CommandReadRAMVar: ram_id=[134, 0]/['?', 'UMainsRMS']

        14 Inverter Power (filtered)
        15 Inverter Power (filtered)
        16 Output power (filtered)
         4 UBat
         5 IBat
        """
        if self.serial is None:
            self.open_port()  # open port

        try:
            ids = [15, 16, 4, 5, 13]  # up to 6x
            self.send_frame('F', [0x06] + ids)
        except IOError:
            self.serial = None
            self.log.error("serial port failed")
        except Exception as e:
            self.log.error("send_snapshot_request: {}".format(e))
            return None

    def send_snapshot_request(self, ram_vars):
        if self.serial is None:
            self.open_port()

        assert ram_vars is not None and len(ram_vars) > 0 and len(ram_vars) <= 6

        try:
            self.send_frame('F', [vebus_constants.F_REQUEST['Snapshot']] + ram_vars)
        except IOError:
            self.serial = None
            self.log.error("serial port failed")
        except Exception as e:
            self.log.error("send_snapshot_request: {}".format(e))
            return None

        

    def read_snapshot_old(self, phase=None):
        """
        007.987 TX: 03 FF 58 38 6E
                          X| 38                         0x38/CommandReadSnapShot

        008.079 RX: 09 FF 58 99 89 FE 05 00 72 01 08
                          X| 99 89 FE 05 00 72 01       0x99/CommandReadSnapShot response: [-375, 5, 370]

        new rx      0B FF 58 99 FF FF FF FF 1C 13 00 00 DA

        # 14 Inverter Power (filtered), +: charge AC>DC -: feed DC>AC
        # 15 Inverter Power(filtered)  falsches Vorzeichen aber genauer am sollwert
        # 16 Output power (filtered)  AC-Output +: out -: in

        ~130ms
        """
        if self.serial is None:
            self.open_port()  # open port

        try:
            if phase:
                self.send_frame('x', [0x38, phase])
            else:
                self.send_frame('X', [0x38])
            frame = self.receive_frame(b'\x0D\xFF\x58')
            if frame[3] != 0x99:
                raise Exception('invalid response')
            # ids = [15, 16, 4, 5, 13] 
            # InverterPower2, OutputPower, UBat, IBat, ChargeState,

            inv_p, out_p, bat_u, bat_i, soc = struct.unpack("<hhhhh", frame[4:4 + 5 * 2])
            r = {'inv_p': -inv_p,
                 'out_p': out_p,
                 'bat_u': round(bat_u / 100, 2),
                 'bat_i': round(bat_i / 10, 1),
                 'bat_p': round(bat_u / 100 * bat_i / 10),
                 'soc': round(soc / 2, 1)}
            self.log.info("read_snapshot: {}".format(r))
            return r
        except IOError:
            self.serial = None
            self.log.error("serial port failed")
        except Exception as e:
            self.log.error("read_snapshot: {}".format(e))
            return None

    def read_snapshot(self, ram_vars, phase=None):
        if self.serial is None:
            self.open_port()  # open port

        try:
            if phase:
                dev_addr=phase -1 # addr starts at 0
                self.send_frame('x', [vebus_constants.WSCommandReadSnapShot, dev_addr])
            else:
                self.send_frame('X', [vebus_constants.WSCommandReadSnapShot])
            frame = self.receive_xyz_frame('X')
#            frame = self.receive_frame(b'\x0D\xFF\x58')
            if frame[3] != 0x99:        # CommandReadSnapShot response must be 0x99
                raise Exception(f"invalid response {frame[3]}")
            
            ret = {}

            for i, ram_var in enumerate(ram_vars):
                print(f"unpach: {frame[4+i*2:4+i*2+2]}")
                v=struct.unpack("<h", frame[4+i*2:4+i*2+2])[0]
                self.log.info(f"read_snapshot: {ram_var}={v}")

#                ret.update({ram_var: v})
                key = next((k for k, v in vebus_constants.RAM_IDS.items() if v == ram_var), f"unknown_{ram_var}")
                v_scale = vebus_constants.RAM_IDS_scale.get(key, lambda x: x)(v)
                ret.update({key: v_scale})

            return ret

        except IOError:
            self.serial = None
            self.log.error("serial port failed")
        except Exception as e:
            self.log.error("read_snapshot: {}".format(e))
            return None

    def read_settings(self, setting_id, phase=None):
        if self.serial is None:
            self.open_port()  # open port
        
        try:
#            setting_id_encoded = struct.pack("<h", setting_id)
            if phase:
                dev_addr=phase -1 # addr starts at 0
                self.send_frame('x', [vebus_constants.WCommandReadSetting, setting_id, dev_addr])
            else:
                self.send_frame('X', [vebus_constants.WCommandReadSetting, setting_id])
            frame = self.receive_xyz_frame('X')
#            frame = self.receive_frame(b'\x0D\xFF\x58')
            
            if frame[3] == vebus_constants.WReplySettingNotSupported:
                logging.warning(f"read_settings: setting {setting_id} not supported")
                return None
            if frame[3] != vebus_constants.WReplyReadSettingOK:
                raise Exception(f"invalid response {frame[3]}")
            
            v=struct.unpack("<H", frame[5:])[0]
            self.log.info(f"read_settings: {setting_id}={v}")
            return v

        except IOError:
            self.serial = None
            self.log.error("serial port failed")
        except Exception as e:
            self.log.error("read_settings: {}".format(e), exc_info=True)
            return None


    def read_ram_var_info(self, ram_var_id):
        if self.serial is None:
            self.open_port()  # open port
        
        try:
#            setting_id_encoded = struct.pack("<h", setting_id)
            self.send_frame('X', [vebus_constants.WCommandGetRAMVarInfo, ram_var_id])
            frame = self.receive_xyz_frame('X')
            
            if frame[3] != vebus_constants.WReplySuccesfulRAMVarInfo:
                raise Exception(f"invalid response {frame[3]}")
            
            (sc, offset) =struct.unpack("<HH", frame[5:5+4])
            self.log.info(f"read_ram_var_info raw: {ram_var_id}={sc} {offset}")

            # see https://github.com/diebietse/invertergui/blob/master/mk2driver/mk2.go

            signed = sc & 0x8000
            
            abs_sc = sc & 0x7FFF  # remove sign bit
            if sc & 0x4000:  # 14th bit set
                print("gt 0x4000")
                sc = 1 / (0x8000 - abs_sc)

            print(f"read_ram_var_info: {ram_var_id}={sc} {offset} signed={signed} abs_sc={abs_sc}")
            return (sc, offset)

        except IOError:
            self.serial = None
            self.log.error("serial port failed")
        except Exception as e:
            self.log.error("read_ram_var_info: {}".format(e), exc_info=True)
            return (None, None)


    def write_ram_var(self, ram_var_id, value, phase=None):
        if self.serial is None:
            self.open_port()  # open port
        
        try:
#            setting_id_encoded = struct.pack("<h", setting_id)
            self.send_frame('X', [vebus_constants.WCommandWriteRAMVar, ram_var_id])
            self.send_frame('X', [vebus_constants.WCommandWriteData, value])

            frame = self.receive_xyz_frame('X')
            
            if frame[3] != vebus_constants.WReplySuccesfulRAMWrite:
                raise Exception(f"invalid response {frame[3]}")

        except IOError:
            self.serial = None
            self.log.error("serial port failed")
        except Exception as e:
            self.log.error("read_ram_var_info: {}".format(e), exc_info=True)
            return (None, None)



    def set_power(self, power):
        """
        Set ESS Power     positiv = charge   negative = feed/discharge,  ~110ms

        013.883 TX: 07 FF 5A 37 00 83 72 01 73  Z| 37 00 83 72 01  !!! SET=370 !!! 0x37/CommandWriteViaID flags=0x00 id=131 data=370
        013.904 RX: 03 FF 5A 87 1D              Z| 87              0x87/CommandWriteViaID response: Write ramvar OK

        new rx :    03 FF 58 87 1F

        :param power: in watt
        :return: True/False
        """
        if self.serial is None:
            self.open_port()  # open port

        try:
            data = struct.pack("<BBBh", 0x37, 0x00, self.ess_setpoint_ram_id, -power)  # cmd, flags, id, power
            self.send_frame('X', data)
            rx = self.receive_frame([b'\x05\xFF\x58', b'\x03\xFF\x58'])  # two different answers are possible
            if rx[3] == 0x87:
                self.log.info("set_ess_power to {}W done".format(power))
                return True
            else:
                raise Exception("invalid response")
        except IOError:
            self.serial = None
            self.log.error("serial port failed")
        except Exception as e:
            self.log.error("set_ess_power: power={} error={}".format(power, e))
            return False

    def set_power_phase(self, power, phase):
        if self.serial is None:
            self.open_port()  # open port

        try:
            data = struct.pack("<BBBhB", 0x37, 0x00, self.ess_setpoint_ram_id, -power, phase-1)  # cmd, flags, id, power
            self.send_frame('x', data)

            data = self.receive_mk2_frame()
            logging.info("got frame {}".format(data))
            if not data or len(data)<4:
                logging.error(f"set_ess_power_3p: invalid frame {data}")
                return False
            
            if chr(data[2]) in 'X':
                if data[3] == 0x87:
                    self.log.info(f"set_ess_power {data[1]} done")
                    return True
                else:
                    self.log.error(f"set_ess_power {data[1]} failed. got {chr(data[2])}")
            else:
                logging.error(f"set_ess_power_3p: invalid frame {data[2]}")
            return False
             
        except IOError:
            self.serial = None
            self.log.error("serial port failed")
        except Exception as e:
            self.log.error("set_ess_power: power={}, phase={} error={}".format(power, phase, e))
            return False



    def set_power_3p(self, power_L1, power_L2, power_L3):
        if self.serial is None:
            self.open_port()  # open port

        try:
            data = struct.pack("<BBBhB", 0x37, 0x00, self.ess_setpoint_ram_id, -power_L1, 0x0)  # cmd, flags, id, power
            self.send_frame('x', data)
            data = struct.pack("<BBBhB", 0x37, 0x00, self.ess_setpoint_ram_id, -power_L2, 0x1)  # cmd, flags, id, power
            self.send_frame('y', data)
            data = struct.pack("<BBBhB", 0x37, 0x00, self.ess_setpoint_ram_id, -power_L3, 0x2)  # cmd, flags, id, power
            self.send_frame('z', data)

            # 05 FF W 87=OK  03 FF W 
            # 0. lenght 
            # 1. 0xFF
            # 2. 0x58 X
            # 3. 40x80 = Command not supported
            # 3. 0x87 = Write ramvar OK
            # 3. 0x88 = Write setting OK
            # 3. 0x9B = Access level required

            waiting_frames = ['X', 'Y', 'Z']
            ok_count=0
            while len(waiting_frames)>0:
                data = self.receive_mk2_frame()
                logging.info("got frame {}".format(data))
                if not data or len(data)<4:
                    logging.error(f"set_ess_power_3p: invalid frame {data}")
                    continue
                if chr(data[2]) in waiting_frames:
                    waiting_frames.remove(chr(data[2]))
                    if data[3] == 0x87:
                        self.log.info(f"set_ess_power {data[1]} done")
                        ok_count+=1
                    else:
                        self.log.error(f"set_ess_power {data[1]} failed. got {chr(data[2])}")
                else:
                    logging.error(f"set_ess_power_3p: invalid frame {data[2]}")
            return ok_count==3
            
            
        except IOError:
            self.serial = None
            self.log.error("serial port failed")
        except Exception as e:
            self.log.error("set_ess_power: power={} error={}".format(power_L1, e))
            return False



    def reset_device(self, device=0):
        data = struct.pack("<BBBBB", 0x8, 0, 0, device, 0)  # cmd, device_id (0=all devices)
        self.send_frame('F', data)
        logging.info("reset done")

    def set_bol(self, iBat_discharge):

        iBat_discharge_dA=int(iBat_discharge*10)
        
        data = struct.pack("<BBBh", 0x9, 0x03, 0x00, iBat_discharge_dA)  # cmd, device_id (0=all devices)
        self.send_frame('F', data)
        rx=self.receive_frame(b'\x07\x3c')
        logging.info(f"set_bol done {rx}")

    def set_ess_modules(self, disable_feed: bool, disable_charge: bool, phase: int):
        if self.serial is None:
            self.open_port()  # open port

        try:
            ess_flag=0
            if disable_charge:
                ess_flag+=0x1
            if disable_feed:
                ess_flag+=0x2

            data = struct.pack("<BBBhB", 0x37, 0x00, self.ess_setpoint_ram_id+1, ess_flag, phase)  # cmd, flags, id, power
            self.send_frame('x', data)
            rx = self.receive_frame([b'\x05\xFF\x58', b'\x03\xFF\x58'])  # two different answers are possible
            if rx[3] == 0x87:
                self.log.info("set_ess_modules to {}W done".format(ess_flag))
                return True
            else:
                self.log.error("set_ess_modules to {}W done".format(ess_flag))

#                raise Exception("invalid response")
        except IOError:
            self.serial = None
            self.log.error("serial port failed")
        except Exception as e:
            self.log.error("set_ess_modules: error={}".format(e))
            return False



    def scan_ess_assistant(self):
        """
        Scan through assistants for ESS

        TX: cmd=X frame=05 FF 58 30 80 00 F4
        RX: frame=07 FF 58 85 90 00 61 59 D3    Assistant SCAN: 128 0x0090
        ...

        128 0x0090  Assistant ID=  9  Following RAMIDs=0
        129 0x8800  Assistant ID=880  Following RAMIDs=0
        130 0x0054  Assistant ID=  5  Following RAMIDs=4   !!! ESS Assistant !!!   005 = ESS  4=SIZE
        131 0x0000
        132 0x0000
        133 0x0000
        134 0x0000
        135 0x00A1  Assistant ID=  A  Following RAMIDs=1

        """
        if self.serial is None:
            self.open_port()  # open port

        ramid = 128
        for n in range(8):
            try:
                data = struct.pack("<BH", 0x30, ramid)  # read ram id
                self.send_frame('X', data)
                rx = self.receive_frame(b'\x07\xFF\x58')
                ram = rx[4] + rx[5] * 256  # value at ramid
                self.log.debug("scan_ess_assistant ramid={} value=0x{:04X}".format(ramid, ram))
                if ram & 0xFFF0 == 0x0050:  # ESS Assistant
                    self.log.info("found ess assistant at ramid={}".format(ramid))
                    self.ess_setpoint_ram_id = ramid + 1
                    return True
                else:
                    ramid += 1 + ram & 0x000F  # skip other
            except IOError:
                self.serial = None
                self.log.error("serial port failed")
            except Exception as e:
                self.log.error("scan_ess_assistant error={}".format(e))
                return False

        self.log.error("ess assistant not found")
        return False

    def format_hex(self, data):
        return " ".join(["{:02X}".format(b) for b in data])

    def send_frame(self, cmd, data):
        frame = self.build_frame(cmd, data)
        self.log.debug("TX: cmd={} frame={}".format(cmd, self.format_hex(frame)))
        self.serial.reset_input_buffer()  # test ob es was hilft ?
        self.serial.write(frame)

    def build_frame(self, cmd, data):
        """
        Build Frame

        :param cmd: byte [2] after 0xFF
        :param data: payload (bytes or list/tuple)
        :return: complete frame in bytes
        """
        frame = bytes((len(data) + 2, 0xFF))  # [length, 0xFF,

        if isinstance(cmd, str):
            frame += bytes((ord(cmd),))
        if isinstance(data, (list, tuple)):
            frame += bytes(data)
        else:
            frame += data
        checksum = 256 - sum(frame) & 0xFF  # calculate checksum
        frame += bytes((checksum,))  # append checksum
        return frame

    def receive_xyz_frame(self, xyz='X', timeout=0.5):
        frame = self.receive_mk2_frame(timeout=timeout)
        if frame[2] == ord(xyz):
            return frame
        else:
            raise Exception("invalid frame {}".format(self.format_hex(frame)))


    def receive_mk2_frame(self, timeout=0.5):
        return self.receive_generic_frame(0xFF, timeout)


    def receive_generic_frame(self, frame_prefix, timeout=0.5):
        """
        Receive frame

        :param head: search pattern (frame start)
        :param timeout:
        :return: frame bytes
        """
        # self.serial.reset_input_buffer()
        rx = bytes()
        tout = time.perf_counter() + timeout
        length = 0
        last_byte=None
        data = bytes()
        start_found=False
        frame_end=False
        crc_byte=None

        pos=0

        while time.perf_counter() < tout and not frame_end: # and pos<len(testdata):
#        while not frame_end and pos<len(testdata):
            next_byte = self.serial.read(1)
            if len(next_byte)==0:
                time.sleep(0.010)
                continue

#            next_byte = testdata[pos]
           # next_byte_as_byte=next_byte.to_bytes(1, byteorder='big')
            next_byte_as_byte=next_byte
            next_byte=int(next_byte_as_byte[0])
            rx += next_byte_as_byte

      #      logging.debug(next_byte)
                          
            if start_found:
                if len(data) == length:
                    crc_byte = next_byte
                    frame_end=True
                else:
                    data += next_byte_as_byte
            elif next_byte == frame_prefix:
                length = last_byte
                data = bytes()
                data += next_byte_as_byte
                
                start_found = True
            elif pos == 0:
                logging.debug(f"got lenght? {next_byte}")
            else:
                logging.debug(f"receive_frame_2: invalid byte {next_byte}, skiping, waiting for {frame_prefix}")
                start_found = False

            last_byte=next_byte
            pos+=1


        if frame_end and crc_byte:
            crc = 256 - sum(rx[:-1]) & 0xFF
            if crc == crc_byte:
                logging.debug(f"receive_frame_2: valid frame {data}, length={len(data)}")
          #      data2=data[1:]
                logging.debug(f"receive_frame_2: valid frame {rx}, length={len(rx)}")
                logging.debug(self.format_hex(rx))
                return rx
            else:
                logging.error(f"receive_frame_2: invalid frame {data}, crc={crc:02X}, crc_byte={crc_byte:02X}")
                data2=data[1:]
                logging.debug(f"receive_frame_2: invalid frame {rx}, length={len(rx)}")
                return rx
        else:
            logging.error(f"receive_frame_2: invalid frame {data}")
            return data
        





            # time.sleep(0.010)
            # if isinstance(head, (list, tuple)):
            #     for h in head:
            #         p = rx.find(h)
            #         if p >= 0:
            #             break
            # else:
            #     p = rx.find(head)

            # if (p >= 0):
            #     flen = rx[p] + 2  # expected full package length
            #     if (len(rx) - p) >= flen:  # rx matches expected full package length
            #         self.log.debug("RX: frame={}".format(self.format_hex(rx[p:p + flen])))
            #         return rx[p:p + flen]

        if rx:
            raise Exception("invalid rx frame {}".format(self.format_hex(rx)))
        else:
            raise Exception("receive timeout, no data")


    def receive_frame(self, head, timeout=0.5):
        """
        Receive frame

        :param head: search pattern (frame start)
        :param timeout:
        :return: frame bytes
        """
        # self.serial.reset_input_buffer()
        rx = bytes()
        tout = time.perf_counter() + timeout
        while time.perf_counter() < tout:
            rx += self.serial.read(500)
            time.sleep(0.010)
            if isinstance(head, (list, tuple)):
                for h in head:
                    p = rx.find(h)
                    if p >= 0:
                        break
            else:
                p = rx.find(head)

            if (p >= 0):
                flen = rx[p] + 2  # expected full package length
                if (len(rx) - p) >= flen:  # rx matches expected full package length
                    self.log.debug("RX: frame={}".format(self.format_hex(rx[p:p + flen])))
                    return rx[p:p + flen]

        if rx:
            raise Exception("invalid rx frame {}".format(self.format_hex(rx)))
        else:
            raise Exception("receive timeout, no data")

    def wakeup(self):
        try:
            self.serial.write(bytes([0x05, 0x3F, 0x07, 0x00, 0x00, 0x00, 0xC2]))
            self.log.info("WAKEUP !!!")
        except IOError:
            self.serial = None
            self.log.error("serial port failed")
        except Exception as e:
            self.log.error("wakeup: {}".format(e))

    def sleep(self):
        """
        Set Multiplus in Sleepmode by command

        Standby consumption: ~1,3 Watt     DC: 27mA AC: 0.0 Watt
        """
        try:
            self.serial.write(bytes([0x05, 0x3F, 0x04, 0x00, 0x00, 0x00, 0xC5]))
            self.log.info("SLEEP !!!")
        except IOError:
            self.serial = None
            self.log.error("serial port failed")
        except Exception as e:
            self.log.error("sleep: {}".format(e))
