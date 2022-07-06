inverter_ip = "192.168.0.33"
inverter_port = 502
# Slave Defaults
# Sungrow: 0x01
# SMA: 3
slave = 0x01
model = "sungrow-sg6kd"
timeout = 5
scan_interval = 10

# Optional:
# dweepy_uuid = "random-uuid"

# optional
# prometheus = True
# prometheus_port = 8000

# Optional:
# influxdb_ip = "192.168.1.128"
# influxdb_port = 8086
# influxdb_user = "user"
# influxdb_password = "password"
# influxdb_database = "inverter"
# influxdb_ssl = True
# influxdb_verify_ssl = False

# Optional
#mqtt_server = "192.168.1.128"
#mqtt_port = 1883
#mqtt_topic = "inverter/stats"
#mqtt_username = "user"
#mqtt_password = "password"

# Optional
#pvoutput_api = "api_key"
#pvoutput_sid = "system_id"
# 60 for regular accounts, 300 for donation accounts
pvoutput_rate_limit = 300

# Meters
dtsu666_port = '/dev/ttyUSB0'
dtsu666_unit = 1
dds578_port = '/dev/ttyUSB0'
dds578_unit = 20

# Optional: save telemetry to a json file
# json_file = "telemetry.json"

# UI
ui_url = "http://127.0.0.1:5000/update"

# Optional: save to a csv file
csv_file_prefix = "data/inverter_data_"