#!/usr/bin/env python3

# Copyright (c) 2017 Dennis Mellican
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

from SungrowModbusTcpClient import SungrowModbusTcpClient
from pymodbus.payload import BinaryPayloadDecoder
from pymodbus.client.sync import ModbusTcpClient
from pymodbus.constants import Endian
from influxdb import InfluxDBClient
from importlib import import_module
from threading import Thread

from prometheus_client import start_http_server, Gauge

import paho.mqtt.client as mqtt
import datetime
import requests
import argparse
import logging
import dweepy
import json
import time
import sys
import re

from dds578_meter import DDS578Meter
from dtsu666_meter import DTSU666Meter
from pvoutputpublisher import PVOutputPublisher

MIN_SIGNED = -2147483648
MAX_UNSIGNED = 4294967295

requests.packages.urllib3.disable_warnings()

# Load in the config module
parser = argparse.ArgumentParser()
parser.add_argument("-c", "--config", default="config", help="Python module to load as our config")
parser.add_argument("-v", "--verbose", action="count", default=0, help="Level of verbosity 0=ERROR 1=INFO 2=DEBUG")
parser.add_argument("--one-shot", action="store_true",
                    help="Run solariot just once then exit, useful for cron based execution")
args = parser.parse_args()

if args.verbose == 0:
    log_level = logging.WARNING
elif args.verbose == 1:
    log_level = logging.INFO
else:
    log_level = logging.DEBUG

logging.basicConfig(level=log_level)

try:
    config = import_module(args.config)
    logging.info(f"Loaded config {config.model}")
except ModuleNotFoundError:
    parser.error(f"Unable to locate {args.config}.py")

# SMA datatypes and their register lengths
# S = Signed Number, U = Unsigned Number, STR = String
sma_moddatatype = {
    "S16": 1,
    "U16": 1,
    "S32": 2,
    "U32": 2,
    "U64": 4,
    "STR16": 8,
    "STR32": 16,
}

# Load the modbus register map for the inverter
modmap_file = f"modbus-{config.model}"

try:
    modmap = import_module(modmap_file)
except ModuleNotFoundError:
    logging.error(f"Unable to locate {modmap_file}.py")
    sys.exit(1)

# This will try the Sungrow client otherwise will default to the standard library.
client_payload = {
    "host": config.inverter_ip,
    "timeout": config.timeout,
    "RetryOnEmpty": True,
    "retries": 3,
    "port": config.inverter_port,
}

t0 = 0
t0_csv = 0


def connect_client():
    if "sungrow-" in config.model:
        logging.info("Creating SungrowModbusTcpClient")
        client = SungrowModbusTcpClient.SungrowModbusTcpClient(**client_payload)
    else:
        logging.info("Creating ModbusTcpClient")
        client = ModbusTcpClient(**client_payload)

    logging.info("Connecting")
    client.connect()
    logging.info("Connected")

    return client


client = connect_client()

# Configure meters
meters = []
if hasattr(config, "dtsu666_port") and hasattr(config, "dtsu666_unit"):
    meters.append(DTSU666Meter(port=config.dtsu666_port, unit=config.dtsu666_unit))
if hasattr(config, "dds578_port") and hasattr(config, "dds578_unit"):
    if hasattr(config, "dtsu666_port") and config.dtsu666_port == config.dds578_port:
        meters.append(DDS578Meter(client=meters[-1].client))
    else:
        meters.append(DDS578Meter(port=config.dds578_port, unit=config.dds578_unit))

# Configure MQTT
if hasattr(config, "mqtt_server"):
    mqtt_client = mqtt.Client(getattr(config, "mqtt_client_name", "pv_data"))

    if hasattr(config, "mqtt_username") and hasattr(config, "mqtt_password"):
        mqtt_client.username_pw_set(config.mqtt_username, config.mqtt_password)

    if config.mqtt_port == 8883:
        mqtt_client.tls_set()

    mqtt_client.connect(config.mqtt_server, port=config.mqtt_port)
    logging.info("Configured MQTT Client")
else:
    mqtt_client = None
    logging.info("No MQTT configuration detected")

if hasattr(config, "prometheus"):
    class PrometheusPublisher(object):
        def __init__(self, port):
            self.publishport = port
            self.metric_mappings = {}
            start_http_server(self.publishport)
            logging.info(f"prometheus: http server started on port {self.publishport}")

        def publish_status(self, metrics):
            for key in metrics.keys():
                if isinstance(metrics[key], str):
                    # skipped because gagues dont handle strings
                    logging.debug(f"prometheus: key {key} skipped(was a string)")
                    continue
                elif not key in self.metric_mappings.keys():
                    logging.info(f"prometheus: key {key} doesnt have a gauge. making one now")
                    self.metric_mappings[key] = Gauge('solar_' + key, key)

                self.metric_mappings[key].set(metrics[key])

        def Clear_status(self):
            for key in self.metric_mappings.keys():
                key.set(0)


    promport = getattr(config, "prometheus_port", "8000")
    prom_client = PrometheusPublisher(promport)
    logging.info("Configured Prometheus Client")
else:
    logging.info("No Prometheus configuration detected")
    prom_client = None

# Configure InfluxDB
if hasattr(config, "influxdb_ip"):
    flux_client = InfluxDBClient(
        config.influxdb_ip,
        config.influxdb_port,
        config.influxdb_user,
        config.influxdb_password,
        config.influxdb_database,
        ssl=config.influxdb_ssl,
        verify_ssl=config.influxdb_verify_ssl,
    )

    logging.info("Configured InfluxDB Client")
else:
    flux_client = None
    logging.info("No InfluxDB configuration detected")

# Configure PVOutput
if hasattr(config, "pvoutput_api"):

    pvoutput_client = PVOutputPublisher(
        config.pvoutput_api,
        config.pvoutput_sid,
        modmap.pvoutput,
        rate_limit=config.pvoutput_rate_limit,
    )

    logging.info("Configured PVOutput Client")
else:
    pvoutput_client = None
    logging.info("No PVOutput configuration detected")

# Inverter Scanning
inverter = {}
bus = json.loads(modmap.scan)


def load_registers(register_type, start, count=100):
    try:
        if register_type == "read":
            rr = client.read_input_registers(
                int(start),
                count=count,
                unit=config.slave,
            )
        elif register_type == "holding":
            rr = client.read_holding_registers(
                int(start),
                count=count,
                unit=config.slave,
            )
        else:
            raise RuntimeError(f"Unsupported register type: {type}")
    except Exception as err:
        logging.warning("No data. Try increasing the timeout or scan interval.")
        return False

    if rr.isError():
        logging.warning("Modbus connection failed")
        client.close()  # close client connection to force reload
        return False

    if not hasattr(rr, 'registers'):
        logging.warning("No registers returned")
        return

    if len(rr.registers) != count:
        logging.warning(f"Mismatched number of registers read {len(rr.registers)} != {count}")
        return

    overflow_regex = re.compile(r"(?P<register_name>[a-zA-Z0-9_\.]+)_overflow$")
    divide_regex = re.compile(r"(?P<register_name>[a-zA-Z0-9_]+)_(?P<divide_by>[0-9\.]+)$")

    for num in range(0, count):
        run = int(start) + num + 1

        if register_type == "read" and modmap.read_register.get(str(run)):
            register_name = modmap.read_register.get(str(run))
            register_value = rr.registers[num]

            # Check if the modbus map has an '_overflow' on the end
            # If so the value 'could' be negative (65535 - x) where (-x) is the actual number
            # So a value of '64486' actually represents '-1049'
            # We rely on a second '_indicator' register to tell is if it's actually negative or not, otherwise it's ambigious!
            should_overflow = overflow_regex.match(register_name)

            if should_overflow:
                register_name = should_overflow["register_name"]

                # Find the indicator register value
                indicator_name = f"{register_name}_indicator"

                for reg_num, reg_name in modmap.read_register.items():
                    if reg_name == indicator_name:
                        indicator_register = int(reg_num)
                        break
                else:
                    indicator_register = None

                if indicator_register is not None:
                    # Given register '5084' and knowing start of '5000' we can assume the index
                    # Of our indicator value is 5084 - 5000 - 1 (because of the 'off by 1')
                    indicator_value = rr.registers[indicator_register - int(start) - 1]

                    if indicator_value == 65535:
                        # We are in overflow
                        register_value = -1 * (65535 - register_value)

            # Check if the modbus map has an '_10' or '_100' etc on the end
            # If so, we divide by that and drop it from the name
            should_divide = divide_regex.match(register_name)

            if should_divide:
                register_name = should_divide["register_name"]
                register_value = float(register_value) / float(should_divide["divide_by"])

            # Set the final register name and value, any adjustments above included
            inverter[register_name] = register_value
        elif register_type == "holding" and modmap.holding_register.get(str(run)):
            register_name = modmap.holding_register.get(str(run))
            register_value = rr.registers[num]

            inverter[register_name] = register_value

    return True


# Function for polling data from the target and triggering writing to log file if set
def load_sma_register(registers):
    # Request each register from datasets, omit first row which contains only column headers
    for thisrow in registers:
        name = thisrow[0]
        startPos = thisrow[1]
        type = thisrow[2]
        format = thisrow[3]

        # If the connection is somehow not possible (e.g. target not responding)
        # show a error message instead of excepting and stopping
        try:
            received = client.read_input_registers(
                address=startPos,
                count=sma_moddatatype[type],
                unit=config.slave
            )
        except Exception:
            thisdate = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            logging.error(f"{thisdate}: Connection not possible, check settings or connection")
            return

        message = BinaryPayloadDecoder.fromRegisters(received.registers, endian=Endian.Big)

        # Provide the correct result depending on the defined datatype
        if type == "S32":
            interpreted = message.decode_32bit_int()
        elif type == "U32":
            interpreted = message.decode_32bit_uint()
        elif type == "U64":
            interpreted = message.decode_64bit_uint()
        elif type == "STR16":
            interpreted = message.decode_string(16)
        elif type == "STR32":
            interpreted = message.decode_string(32)
        elif type == "S16":
            interpreted = message.decode_16bit_int()
        elif type == "U16":
            interpreted = message.decode_16bit_uint()
        else:
            # If no data type is defined do raw interpretation of the delivered data
            interpreted = message.decode_16bit_uint()

        # Check for "None" data before doing anything else
        if ((interpreted == MIN_SIGNED) or (interpreted == MAX_UNSIGNED)):
            displaydata = None
        else:
            # Put the data with correct formatting into the data table
            if format == "FIX3":
                displaydata = float(interpreted) / 1000
            elif format == "FIX2":
                displaydata = float(interpreted) / 100
            elif format == "FIX1":
                displaydata = float(interpreted) / 10
            else:
                displaydata = interpreted

        logging.debug(f"************** {name} = {displaydata}")
        inverter[name] = displaydata

    # Add timestamp
    inverter["00000 - Timestamp"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def publish_prometheus(inverter):
    result = prom_client.publish_status(inverter)
    if result:
        logging.info("Published to prometheus")


def publish_influx(metrics):
    target = flux_client.write_points([metrics])
    logging.info("Published to InfluxDB")
    return target


def publish_dweepy(inverter):
    result = dweepy.dweet_for(config.dweepy_uuid, inverter)
    logging.info("Published to dweet.io")
    return result


def publish_mqtt(inverter):
    # After a while you'll need to reconnect, so just reconnect before each publish
    mqtt_client.reconnect()

    result = mqtt_client.publish(config.mqtt_topic, json.dumps(inverter).replace('"', '\"'))
    result.wait_for_publish()

    if result.rc != mqtt.MQTT_ERR_SUCCESS:
        # See https://github.com/eclipse/paho.mqtt.python/blob/master/src/paho/mqtt/client.py#L149 for error code mapping
        logging.error(f"Failed to publish to MQTT with error code: {result.rc}")
    else:
        logging.info("Published to MQTT")

    return result


def publish_ui(inverter):
    response = requests.post(url=config.ui_url, json=inverter)
    if response.status_code != requests.codes.ok:
        logging.error("Error publishing to ui")
    else:
        logging.info("Published data to ui")


def publish_pvoutput(inverter):
    result = pvoutput_client.publish_status(inverter)

    if result == "skipped":
        logging.info("Skipping PVOutput to stay under the rate limit")
    else:
        logging.info("Published to PVOutput")
    return result


def save_json(inverter):
    try:
        f = open(config.json_file, 'w')
        f.write(json.dumps(inverter))
        f.close()
    except Exception as err:
        logging.error("Error writing telemetry to file: %s" % err)
        return
    logging.info("Inverter telemetry written to %s file." % config.json_file)


def save_csv(inverter):
    global t0_csv
    if (time.time() - t0_csv) < 60:
        logging.info("Skipping csv file, t < 60s")
        return
    try:
        now = datetime.datetime.now()
        with open(config.csv_file_prefix + now.strftime("%Y%m%d") + ".csv", 'a') as fp:
            string = f"{now.strftime('%H:%M:%S')},"
            for metric in ("Energy Generation", "Power Generation", "Temperature", "Voltage", "Active Power", "v7"):
                if metric in modmap.pvoutput:
                    try:
                        string += f"{inverter[modmap.pvoutput.get(metric)]},"
                    except KeyError:
                        string += f","
            fp.write(string + "\n")
    except Exception as err:
        logging.error("Error writing telemetry to file: %s" % err)
        return
    logging.info("Inverter telemetry written to csv file.")
    t0_csv = time.time()


# Core monitoring loop
def scrape_inverter():
    """ Connect to the inverter and scrape the metrics """

    global client
    # Connect only if disconnected
    if not client.is_socket_open():
        client = connect_client()

    if "sungrow-" in config.model:
        for i in bus["read"]:
            if not load_registers("read", i["start"], int(i["range"])):
                return False

        for i in bus["holding"]:
            if not load_registers("holding", i["start"], int(i["range"])):
                return False

        # Sungrow inverter specifics:
        # Work out if the grid power is being imported or exported
        if config.model == "sungrow-sh5k":
            try:
                if inverter["grid_import_or_export"] == 65535:
                    export_power = (65535 - inverter["export_power"]) * -1
                    inverter["export_power"] = export_power
            except Exception:
                pass

        try:
            inverter["timestamp"] = "%s/%s/%s %s:%02d:%02d" % (
                inverter["day"],
                inverter["month"],
                inverter["year"],
                inverter["hour"],
                inverter["minute"],
                inverter["second"],
            )
        except Exception:
            pass
    elif "sma-" in config.model:
        load_sma_register(modmap.sma_registers)
    else:
        raise RuntimeError(f"Unsupported inverter model detected: {config.model}")

    return True


while True:
    # Wait for next scan time
    waittime = config.scan_interval - (time.time() - t0)
    if waittime > 0:
        logging.info(f"waiting {waittime} for the next cycle")
        time.sleep(waittime)
    t0 = time.time()
    # Clear inverter var
    inverter = {}
    # Scrape meters
    success = True
    if len(meters) > 0:
        meter_data = {}
        for meter in meters:
            try:
                meter_data.update(meter.query())
                time.sleep(0.1)
            except:
                logging.error("Error scraping meters")
                success = False
        inverter.update(meter_data)

    # Scrape the inverter
    success = scrape_inverter() or success  # consider meter-only readings as success

    logging.info(f"inverter: {inverter}")

    if not success:
        # reset counters otherwise prometheus will keep on reporting whatever was pushed last
        if prom_client is not None:
            prom_client.Clear_status()
            logging.warning("Failed to scrape inverter, skipping this scan")
        continue

    # Optionally publish the metrics if enabled
    if mqtt_client is not None:
        t = Thread(target=publish_mqtt, args=(inverter,))
        t.start()

    if hasattr(config, "dweepy_uuid"):
        t = Thread(target=publish_dweepy, args=(inverter,))
        t.start()

    if prom_client is not None:
        t = Thread(target=publish_prometheus, args=(inverter,))
        t.start()

    if flux_client is not None:
        metrics = {
            "measurement": "Sungrow",
            "tags": {
                "location": "Gabba",
            },
            "fields": inverter,
        }

        t = Thread(target=publish_influx, args=(metrics,))
        t.start()

    if pvoutput_client is not None:
        t = Thread(target=publish_pvoutput, args=(inverter,))
        t.start()

    if hasattr(config, "json_file"):
        t = Thread(target=save_json, args=(inverter,))
        t.start()

    if hasattr(config, "csv_file_prefix"):
        t = Thread(target=save_csv, args=(inverter,))
        t.start()

    if hasattr(config, "ui_url"):
        t = Thread(target=publish_ui, args=(inverter,))
        t.start()

    if args.one_shot:
        logging.info("Exiting due to --one-shot")
        break
