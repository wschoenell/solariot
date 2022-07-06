import json

from flask import Flask, request

app = Flask(__name__)

data = {}


@app.route("/")
def main():
    ret = "<table align='center'>"
    for key in ("Total Active Electricity Power", "Total_import_kwh", "Total_export_kwh", "Total_System_Active_Power"):
        if key in data:
            value = data.pop(key)
            value = f"{value:.2f}" if isinstance(value, float) else value
            ret += f'<tr align="center"> <td class="">{key}</td> <td class="">{value}</td> </tr>'
    for key, value in data.items():
        value = f"{value:.2f}" if isinstance(value, float) else value
        ret += f'<tr align="center"> <td class="">{key}</td> <td class="">{value}</td> </tr>'
    ret += "</table>"
    return ret


@app.route("/update", methods=['GET', 'POST'])
def update():
    global data
    if request.is_json:
        data = request.json
    return "ok"


if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)
