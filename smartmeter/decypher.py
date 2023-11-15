from gurux_dlms.GXByteBuffer import GXByteBuffer
from binascii import unhexlify
from gurux_dlms.GXDLMSTranslator import GXDLMSTranslator
from gurux_dlms.GXDLMSTranslatorMessage import GXDLMSTranslatorMessage
from bs4 import BeautifulSoup
import lxml

class decypher:
    def __init__(self, key):
        self.key = key
        self.tr = GXDLMSTranslator()
        self.tr.blockCipherKey = GXByteBuffer(key)
        self.tr.comments = True

    def decrypt(self, daten):
        msg = GXDLMSTranslatorMessage()
        msg.message = GXByteBuffer(daten)
        xml = ""
        pdu = GXByteBuffer()
        self.tr.completePdu = True
        while self.tr.findNextFrame(msg, pdu):
            pdu.clear()
            xml += self.tr.messageToXml(msg)

        soup = BeautifulSoup(xml, 'lxml')

        results_32 = soup.find_all('uint32')

        data = {
            "power_in": 0,
            "power_out": 0,
            "power": 0,
            "power_unit": "W",
            "total_in": 0,
            "total_out": 0
        }

        data["total_in"] = int(results_32[0]["value"], 16)/1000
        data["total_out"] = int(results_32[1]["value"], 16)/1000
        #data["blind_in"] = int(results_32[2]["value"], 16)/1000
        #data["blind_out"] = int(results_32[3]["value"], 16)/1000
        data["power_in"] = int(results_32[4]["value"], 16)
        data["power_out"] = int(results_32[5]["value"], 16)
        data["power"] = int(results_32[4]["value"], 16) - int(results_32[5]["value"], 16)
        return data
