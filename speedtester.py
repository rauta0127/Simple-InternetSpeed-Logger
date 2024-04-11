import time
import time
import pandas as pd
import subprocess
import multiprocessing
from multiprocessing import Process
import json
import logging
from logging import getLogger, config
import speedtest_cli
from dateutil import tz

with open('./log_config.json', 'r') as f:
    log_conf = json.load(f)

config.dictConfig(log_conf)
logger = getLogger("speedtester")

class WifiConnectionError(Exception):
    def __init__(self, message):
        super().__init__(message)

class SpeedtestError(Exception):
    def __init__(self, message):
        super().__init__(message)


def exec_speedtest():
    """
    Ref: https://github.com/sivel/speedtest-cli/wiki
    """
    start_time = time.time()
    results_dict = {}
    try:
        results_dict = speedtest_cli.shell()
    except Exception as e:
        logger.error(f'ERROR Exception: {e}')
    end_time = time.time()
    elapsed_time = end_time - start_time
    return results_dict, elapsed_time


def convert_format_to_dataframe(results_dict):
    base_keys = [
        "download",
        "upload",
        "ping",
        "timestamp",
        "bytes_sent",
        "bytes_received",
        "share",
    ]
    assert type(results_dict) == str
    results_dict = json.loads(results_dict)
    base_results_df = pd.DataFrame([[results_dict[k] for k in base_keys]], columns=base_keys).reset_index(drop=True)
    from_zone = tz.tzutc()
    to_zone = tz.tzlocal()
    base_results_df["timestamp_local"] = pd.to_datetime(base_results_df["timestamp"]).map(lambda x: x.replace(tzinfo=from_zone).astimezone(to_zone))
    server_results_dict = results_dict["server"]
    server_results_df = (
        pd.DataFrame.from_dict(server_results_dict, orient="index").T.add_prefix("server_").reset_index(drop=True)
    )
    client_results_dict = results_dict["client"]
    client_results_df = (
        pd.DataFrame.from_dict(client_results_dict, orient="index").T.add_prefix("client_").reset_index(drop=True)
    )
    df = pd.concat([base_results_df, server_results_df, client_results_df], axis=1).reset_index(drop=True)
    return df


def get_vpn_list():
    """
    This VPN List may be wrong.
    """
    cmd = subprocess.run(
        "networksetup -listallnetworkservices",
        capture_output=True,
        text=True,
        shell=True,
    )
    vpn_list = [
        s
        for s in cmd.stdout.split("\n")
        if s
        not in [
            "An asterisk (*) denotes that a network service is disabled.",
            "USB 10/100/1000 LAN",
            "Wi-Fi",
            "iPhone USB",
            "Thunderbolt Bridge",
            "",
        ]
    ]
    return vpn_list


def get_connected_vpn(vpn_list):
    connected_vpn = None
    for vpn in vpn_list:
        cmd = subprocess.run(
            f'networksetup -showpppoestatus "{vpn}"',
            capture_output=True,
            text=True,
            shell=True,
        )
        connected = [
            s
            for s in cmd.stdout.split("\n")
            if s
            not in [
                "",
            ]
        ][0]
        if connected == "connected":
            connected_vpn = vpn
            break
    return connected_vpn

def get_current_wifi_physical_name():
    wifi_physical_name = None
    cmd = subprocess.run(
        "networksetup -getairportnetwork en0",
        capture_output=True,
        text=True,
        shell=True,
    )
    if cmd.stdout:
        if "Wi-Fi power is currently off" in cmd.stdout:
            message = cmd.stdout.replace("\n", "\\n")
            raise WifiConnectionError(message)
        else:
            wifi_physical_name = [
                s
                for s in cmd.stdout.split("\n")
                if s
                not in [
                    "",
                ]
            ][
                0
            ].replace("Current Wi-Fi Network: ", "")
    return wifi_physical_name


class SpeedTester:
    def __init__(self, frequency: int = 20, iterations: int = 10):
        self.frequency = frequency
        self.iterations = iterations
        self.elapsed_iterations = 0
        self.remained_iterations = iterations
        self.pause = False
        self.done = False
        self.active = False
        self.start_time = None
        self.elapsed_iterations_at_pause = 0

    def get_status_string(self):
        status_string = ""
        if not self.start_time:
            status_string = "Ready"
        if self.done:
            status_string = "Done"
        if self.pause:
            status_string = "Paused"
        if self.active and not self.done and not self.pause:
            status_string = "Working"
        status_string += f"({self.elapsed_iterations}/{self.iterations}it/{self.frequency}sec)"
        return status_string

    def start(self):
        self.active = True
        self.pause = False
        self.done = False
        self.start_time = time.time()
        logger.info("SpeedTester started")

    def restart(self):
        self.active = True
        self.pause = False
        self.done = False
        logger.info("SpeedTester restarted")

    def pause_iterations(self):
        self.active = False
        self.pause = True
        self.elapsed_iterations_at_pause = self.elapsed_iterations
        logger.info("SpeedTester paused")

    def measure_subprocess(self, log_queue: multiprocessing.Queue):
        logger.info(f"Start measuring in subprocess")
        try:
            records_df = pd.read_csv("records.csv")
        except:
            records_df = pd.read_csv("records_init.csv")

        wifi_physical_name = None
        connected_vpn = None
        try:
            wifi_physical_name = get_current_wifi_physical_name()
            logger.info(f"wifi_physical_name: {wifi_physical_name}")
        except Exception as e:
            logger.error(f"Caused {type(e).__name__}: {e}")
            return records_df

        try:
            vpn_list = get_vpn_list()
            if len(vpn_list) > 0:
                connected_vpn = get_connected_vpn(vpn_list)
        except Exception as e:
            logger.error(f"Caused {type(e).__name__}: {e}")
            return records_df

        try:
            results_dict, elapsed_time = exec_speedtest()
        except Exception as e:
            logger.error(f"Caused {type(e).__name__}: {e}")
            return records_df
        
        try:
            after_wifi_physical_name = get_current_wifi_physical_name()
        except Exception as e:
            logger.error(f"Caused {type(e).__name__}: {e}")
            return records_df
        
        if wifi_physical_name != after_wifi_physical_name:
            message = "wifi_physical_name changed during measuring. (before={wifi_physical_name}, after={after_wifi_physical_name})"
            logger.error(f"Caused error: {message}")
            return records_df
        else:
            try:
                new_records_df = convert_format_to_dataframe(results_dict)
                new_records_df["wifi_physical_name"] = wifi_physical_name
                new_records_df["connected_vpn"] = connected_vpn
                new_records_df["pid"] = multiprocessing.current_process().pid
                new_records_df["elapsed_time"] = elapsed_time
                records_df = pd.concat([records_df, new_records_df], axis=0).reset_index(drop=True)
                records_df.to_csv("records.csv", index=False)
                logger.info(f"Completed subprocess successfully")
            except Exception as e:
                logger.error(f"Caused error in subprocess: {e}")

        return records_df

    def measure(self):
        log_queue = multiprocessing.Queue()
        listener = logging.handlers.QueueListener(log_queue, *logger.handlers)
        listener.start()

        flg = False
        if self.remained_iterations <= 0 and self.active:
            self.remained_iterations = 0
            self.done = True
            self.active = False
        elif self.active and not self.done:
            logger.info(f"Start measuring: {self.get_status_string()}")
            process = Process(target=self.measure_subprocess, args=(log_queue,))
            process.start()
            time.sleep(0.5)
            self.elapsed_iterations += 1
            self.remained_iterations = self.iterations - self.elapsed_iterations
            flg = True

        return flg

    def set_params(self, frequency, iterations):
        self.frequency = frequency
        self.iterations = iterations
        self.reset()
        logger.info(f"Set new parameters: frequency={self.frequency}, iterations={self.iterations}")

    def reset(self):
        self.done = False
        self.active = False
        self.pause = False
        self.start_time = None
        self.elapsed_iterations = 0
        self.remained_iterations = self.iterations
        self.elapsed_iterations_at_pause = 0
        


if __name__ == "__main__":
    frequency = 20
    iterations = 3
    speedtester = SpeedTester(frequency, iterations)
    speedtester.start()
    while not speedtester.done:
        speedtester.measure()
        time.sleep(frequency)
