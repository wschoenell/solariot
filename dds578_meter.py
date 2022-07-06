from pymodbus.client.sync import ModbusSerialClient
from pymodbus.constants import Endian
from pymodbus.payload import BinaryPayloadDecoder


class DDS578Meter(object):
    def __init__(self, port='/dev/ttyUSB0', baudrate=9600, unit=20, client=None):
        if client is not None:
            self.client = client
        else:
            self.client = ModbusSerialClient(method='rtu', port=port, baudrate=baudrate)
        self.client.connect()

        self.register_addrs = {0: {
            'A Voltage': 0,
            'B Voltage': 0x2,
            'C Voltage': 0x4,
            'A Current': 0x8,
            'B Current': 0x0A,
            'C Current': 0x0C,
            'Total Active Power': 0x10,
            'A Active Power': 0x12,
            'B Active Power': 0x14,
            'C Active Power': 0x16,
            'Total Reactive Power': 0x18,
            'A Reactive Power': 0x1A,
            'B Reactive Power': 0x1C,
            'C Reactive Power': 0x1E,
            'A Power Factor': 0x2A,
            'B Power Factor': 0x2C,
            'C Power Factor': 0x2E,
            'Frequency': 0x36,
        },
            256: {"Total Active Electricity Power": 0x0},
            1024: {"Total Reactive Electricity Power": 0x0},
        }

        self.unit = unit

    def query(self):
        ret = {}
        for addr, registers in self.register_addrs.items():
            result = self.client.read_input_registers(addr, 56, unit=self.unit)

            for key, val in registers.items():
                decoder = BinaryPayloadDecoder.fromRegisters([result.registers[r] for r in [val, val + 1]], Endian.Big,
                                                             wordorder=Endian.Big)
                ret.update({key: decoder.decode_32bit_float()})
        return ret

    def __del__(self):
        self.client.close()


if __name__ == "__main__":
    meter = DDS578Meter()
    print(meter.query())
    del meter
