import logging
import datetime

import requests

dry_run = False

class PVOutputPublisher(object):
    def __init__(self, api_key, system_id, metric_mappings, rate_limit=60,
                 status_url="https://pvoutput.org/service/r2/addstatus.jsp"):
        self.api_key = api_key
        self.system_id = system_id
        self.status_url = status_url
        self.metric_mappings = metric_mappings
        self.rate_limit = rate_limit

        self.latest_run = None

    @property
    def headers(self):
        return {
            "X-Pvoutput-Apikey": self.api_key,
            "X-Pvoutput-SystemId": self.system_id,
            "Content-Type": "application/x-www-form-urlencoded",
            "cache-control": "no-cache",
        }

    def publish_status(self, metrics):
        """
        See https://pvoutput.org/help/api_specification.html#add-status-service
        Post the following values:
        * v1 - Energy Generation
        * v2 - Power Generation
        * v3 - Energy Consumption
        * v4 - Power Consumption
        * v5 - Temperature
        * v6 - Voltage
        """
        at_least_one_of = {"v1", "v2", "v3", "v4"}

        now = datetime.datetime.now()

        if self.latest_run:
            # Spread out our publishes over the hour based on the rate limit
            time_diff = (now - self.latest_run).total_seconds()

            if time_diff < (3600 / self.rate_limit):
                return "skipped"

        parameters = {
            "d": now.strftime("%Y%m%d"),
            "t": now.strftime("%H:%M"),
            "c1": 1,
        }

        if self.metric_mappings.get("Energy Generation") in metrics:
            parameters["v1"] = metrics[self.metric_mappings.get("Energy Generation")]

        if self.metric_mappings.get("Power Generation") in metrics:
            parameters["v2"] = metrics[self.metric_mappings.get("Power Generation")]

        if self.metric_mappings.get("Energy Consumption") in metrics:
            parameters["v3"] = metrics[self.metric_mappings.get("Energy Consumption")]

        if self.metric_mappings.get("Power Consumption") in metrics:
            parameters["v4"] = metrics[self.metric_mappings.get("Power Consumption")]
        elif self.metric_mappings.get("Active Power") in metrics:
            parameters["v4"] = metrics[self.metric_mappings.get("Active Power")]
            if self.metric_mappings.get("Power Generation") in metrics:
                parameters["v4"] += metrics[self.metric_mappings.get("Power Generation")]

        if self.metric_mappings.get("Temperature") in metrics:
            parameters["v5"] = metrics[self.metric_mappings.get("Temperature")]

        if self.metric_mappings.get("Voltage") in metrics:
            parameters["v6"] = metrics[self.metric_mappings.get("Voltage")]

        for v in range(7, 13):
            if self.metric_mappings.get(f"v{v}") in metrics:
                parameters[f"v{v}"] = metrics[self.metric_mappings.get(f"v{v}")]

        if not at_least_one_of.intersection(parameters.keys()):
            raise RuntimeError("Metrics => PVOutput mapping failed, please review metric names and update")

        logging.info(f"Publishing on PVOutput: {parameters}, metrics: {metrics}")

        if not dry_run:
            response = requests.post(url=self.status_url, headers=self.headers, params=parameters)

            if response.status_code != requests.codes.ok:
                raise RuntimeError(response.text)

        logging.debug("Successfully posted status update to PVOutput")
        self.latest_run = now
