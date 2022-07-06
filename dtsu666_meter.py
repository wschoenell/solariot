from pymodbus.client.sync import ModbusSerialClient
from pymodbus.constants import Endian
from pymodbus.payload import BinaryPayloadDecoder


class DTSU666Meter(object):
    def __init__(self, port='/dev/ttyUSB0', baudrate=9600, unit=1, client=None):
        if client is not None:
            self.client = client
        else:
            self.client = ModbusSerialClient(method='rtu', port=port, baudrate=baudrate)
        self.client.connect()

        self.register_addrs = {"Volts_AB": 0x2000,
                               "Volts_BC": 0x2002,
                               "Volts_CA": 0x2004,
                               "Volts_L1": 0x2006,
                               "Volts_L2": 0x2008,
                               "Volts_L3": 0x200A,
                               "Current_L1": 0x200C,
                               "Current_L2": 0x200E,
                               "Current_L3": 0x2010,
                               "Active_Power_L1": 0x2014,
                               "Active_Power_L2": 0x2016,
                               "Active_Power_L3": 0x2018,
                               "Reactive_Power_L1": 0x201C,
                               "Reactive_Power_L2": 0x201E,
                               "Reactive_Power_L3": 0x2020,
                               "Power_Factor_L1": 0x202C,
                               "Power_Factor_L2": 0x202E,
                               "Power_Factor_L3": 0x2030,
                               "Total_System_Active_Power": 0x2012,
                               "Total_System_Reactive_Power": 0x201A,
                               "Total_System_Power_Factor": 0x202A,
                               "Frequency_Of_Supply_Voltages": 0x2044,
                               "Total_import_kwh": 0x401E,
                               "Total_export_kwh": 0x4028,
                               "Total_Q1_kvarh": 0x4028,
                               "Total_Q2_kvarh": 0x403C,
                               "Total_Q3_kvarh": 0x4046,
                               "Total_Q4_kvarh": 0x4050
                               }

        self.unit = unit

    def query(self):
        ret = {}
        for register_name, addr in self.register_addrs.items():
            result = self.client.read_holding_registers(addr, 2, unit=self.unit)

            decoder = BinaryPayloadDecoder.fromRegisters(result.registers, Endian.Big, wordorder=Endian.Big)
            ret.update({register_name: decoder.decode_32bit_float()})
        # Convert units
        for k, v in ret.items():
            if any(x in k for x in ("Volts", "_Power")):
                ret.update({k: v * .1})
            elif any(x in k for x in ("Frequency",)):
                ret.update({k: v * .01})
            elif any(x in k for x in ("Power_Factor",  "Current")):
                ret.update({k: v * .001})

        return ret

    def __del__(self):
        self.client.close()


if __name__ == "__main__":
    import time
    import datetime

    # from dds578_meter import DDS578Meter

    meter1 = DTSU666Meter()
    meter2 = DDS578Meter(client=meter1.client)

    while True:
        print(datetime.datetime.now().isoformat())
        print(meter1.query())
        time.sleep(0.1)
        print(meter2.query())
        time.sleep(10)
    # del meter1, meter2
