import rumps
import time
import pandas as pd
import os
import json
from logging import getLogger, config
from speedtester import SpeedTester
from pathlib import Path
import shutil
from datetime import datetime
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dateutil import tz

app_name = "Simple-InternetSpeed-Logger"
with open('./log_config.json', 'r') as f:
    log_conf = json.load(f)

config.dictConfig(log_conf)
logger = getLogger("app")


class SpeedtestLoggerStatusBarApp(rumps.App):
    def __init__(self, frequency: int = 10, iterations: int = 10):
        super(SpeedtestLoggerStatusBarApp, self).__init__(name=app_name, template=True)
        self.icon = "icon.png"
        self.frequency = frequency
        self.iterations = iterations
        self.speedtester = SpeedTester(self.frequency, self.iterations)
        self.status = rumps.MenuItem(self.speedtester.get_status_string())
        self.menu = ["[InternetSpeed Logger]", self.status]
        self.rumps_timer = rumps.Timer(callback=self.measure, interval=self.frequency)
        self.rumps_timer.callback(self.measure)
        self.downloads_dir = str(Path.home()/"Downloads")

    def change_status(self):
        self.status.title = self.speedtester.get_status_string()

    def notification(self, title, subtitle, message, data=None, sound=True):
        try:
            rumps.notification(
                title=title, 
                subtitle=subtitle,
                message=message, 
                data=None, 
                sound=True
            )
        except RuntimeError as e:
            e = str(e).replace("\n", "\\n")
            logger.error(f"RuntimeError: {e}")
        return None


    def measure(self, _):
        if self.speedtester.measure():
            self.notDone = True
            self.invert_counter = 0
            self.change_status()

        if self.speedtester.done:
            if self.notDone:
                self.notDone = False
                self.rumps_timer.stop()
                self.reset()
                self.notification(
                    title="Speedtest Logger App", 
                    subtitle="Speedtest Done.",
                    message="", 
                    data=None, 
                    sound=True
                )
                logger.info(f"Speedtester Done")

    @rumps.clicked("Start", key="s")
    def pause(self, sender):
        logger.info(f"Clicked {sender.title}")
        if sender.title == "Pause":
            self.speedtester.pause_iterations()
            self.rumps_timer.stop()
            sender.title = "Restart"
            self.change_status()
        elif sender.title == "Start":
            self.speedtester.start()
            self.rumps_timer.start()
            self.notification(
                title="Speedtest Logger App", 
                subtitle="Speedtest Start.",
                message="", 
                data=None, 
                sound=True
            )
            sender.title = "Pause"
            self.change_status()
        elif sender.title == "Restart":
            self.speedtester.restart()
            self.rumps_timer.start()
            sender.title = "Pause"
            self.change_status()

    @rumps.clicked("Reset", key="r")
    def reset_button(self, sender):
        logger.info(f"Clicked Reset")
        self.reset()
        self.menu["Start"].title = "Start"
        logger.info(f"Reseted")

    def reset(self):
        self.speedtester.reset()
        self.rumps_timer.stop()
        self.reset_timer()
        self.change_status()
        self.menu["Start"].title = "Start"

    def reset_timer(self):
        self.rumps_timer = rumps.Timer(callback=self.measure, interval=self.frequency)
        self.rumps_timer.callback(self.measure)

    @rumps.clicked("Export Plot")
    def export_plot(self, _):
        try:
            records_df = pd.read_csv("records.csv")
        except:
            records_df = pd.read_csv("records_init.csv")
        if len(records_df) > 0:
            self.plot(records_df)
        else:
            rumps.alert(f"Records has 0 data.")
            logger.warning(f"Records has 0 data.")


    def plot(self, records_df):
        df = records_df[["timestamp", "wifi_physical_name", "connected_vpn", "download", "upload"]].copy()
        df["Network"] = df["wifi_physical_name"] + "(" + df["connected_vpn"] + ")"
        df.loc[pd.isnull(df["connected_vpn"]), "Network"] = df.loc[pd.isnull(df["connected_vpn"]), "wifi_physical_name"]
        main_network = df.groupby("Network").size().sort_values(ascending=False).index.tolist()[0]

        fig = make_subplots(
            rows=2, 
            cols=2,
            subplot_titles=("Network Speed Distirbution", "Record Counts", f"DownloadSpeedHeatmap({main_network})"),
            specs=[
                [{"colspan": 2}, None],
                [{}, {}]
            ]
        )

        # By Wifi boxplot
        for direction in ["download", "upload"]:
            fig.add_trace(
                go.Box(
                    y=df[direction],
                    x=df["Network"],
                    name=direction,
                    legendgroup="1",
                    showlegend=True
                ),
                row=1, col=1,
            )

        netowrk_size_df = df.groupby("Network").size().reset_index(name="Counts")
        fig.add_trace(
            go.Bar(
                x=netowrk_size_df["Network"], 
                y=netowrk_size_df["Counts"],
                legendgroup="2",
                showlegend=False
            ),
            row=2, col=1
        )

        # Dayofweek/Hour Heatmap 
        from_zone = tz.tzutc()
        to_zone = tz.tzlocal()
        df["timestamp"] = pd.to_datetime(df["timestamp"]).map(lambda x: x.replace(tzinfo=from_zone).astimezone(to_zone))
        df["dayofweek"] = df["timestamp"].dt.dayofweek
        dayofweek_dict = {
            0: "1.Monday",
            1: "2.Tuesday",
            2: "3.Wednesday",
            3: "4.Thursday",
            4: "5.Friday",
            5: "6.Saturday",
            6: "7.Sunday",
        }
        df["dayofweek"] = df["dayofweek"].map(lambda x: dayofweek_dict.get(x))
        df["hour"] = df["timestamp"].dt.hour
        main_network_df = df.groupby("Network").get_group(main_network)
        pivot_df = pd.pivot_table(data=main_network_df, index="dayofweek", columns="hour", values="download", aggfunc="mean")
        fig.add_trace(
            go.Heatmap(
                z=pivot_df.values,
                x=pivot_df.columns, 
                y=pivot_df.index,
                legendgroup="3",
                showlegend=False
            ),
            row=2, col=2
        )

        now = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        fig.update_layout(
            boxmode='group', 
            title_text=f"{app_name} ({now})",
            legend_tracegroupgap = 180,
            showlegend=False
        )
        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = f"{self.downloads_dir}/{app_name}_plot_{now}.html"
        fig.write_html(filepath)
        time.sleep(0.5)
        rumps.alert(f"Exported plot successfully: {filepath}")
        logger.info(f"Exported plot successfully: {filepath}")

    @rumps.clicked("Export CSV")
    def export_csv(self, _):
        try:
            records_df = pd.read_csv("records.csv")
        except:
            records_df = pd.read_csv("records_init.csv")
        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = f"{self.downloads_dir}/{app_name}_csv_{now}.csv"
        records_df.to_csv(filepath, index=False)
        time.sleep(0.5)
        rumps.alert(f"Exported as csv successfully: {filepath}")
        logger.info(f"Exported as csv successfully: {filepath}")

    @rumps.clicked("Export Log")
    def export_log(self, _):
        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = f"{self.downloads_dir}/{app_name}_log_{now}.log"
        shutil.copy('logs.log', filepath)
        time.sleep(0.5)
        rumps.alert(f"Exported log file successfully: {filepath}")
        logger.info(f"Exported log file successfully: {filepath}")

    def validate_input(self, text):
        texts = text.split(",")
        if len(texts) != 2:
            return "Input format is [int,int]. Please check."

        frequency = texts[0]
        try:
            int(frequency)
            if int(frequency) < 20:
                return "Frequency should be larger than 20"
            if int(frequency) >= 60 * 60:
                return "Frequency should be less than 3600"
        except:
            return "Frequency should be integer"

        iterations = texts[1]
        try:
            int(iterations)
            if int(iterations) <= 0:
                return "Iterations should be larger than 0"
            if int(iterations) >= 1000:
                return "Iterations should be less than 1000"
        except:
            return "Iterations should be integer"
        return "OK"

    @rumps.clicked("Setting")
    def setting(self, _):
        logger.info(f"Clicked Setting")
        self.reset()
        response = rumps.Window(
            message="""
            Set Parameters. \n
            (Format: frequency,iterations) \n
            * frequency: int, >20, < 3600 sec \n
            * iterations: int, >0, < 1000
            """,
            default_text="20,10",
            cancel="Cancel",
            dimensions=(120, 20)
        ).run()
        if response.clicked:
            if response.text == "":
                rumps.alert("Your input is blank.")

            validate_result = self.validate_input(response.text)
            if validate_result != "OK":
                rumps.alert(f"Your input is invalid. {validate_result}")

            else:
                (frequency, iterations) = response.text.split(",")
                self.frequency = int(frequency)
                self.iterations = int(iterations)
                self.speedtester.set_params(self.frequency, self.iterations)
                self.change_status()

    @rumps.clicked("Erase All Data")
    def erase_all_data(self, _):
        logger.info(f"Clicked Erase All Data")
        response = rumps.alert(
            message="""
            Erase All Data? (CSV and Log files)
            """,
            cancel="Cancel",
        )
        if response == 1:
            if os.path.exists("records.csv"):
                os.remove("records.csv")
            if os.path.exists("logs.log"):
                os.remove("logs.log")
            rumps.alert("Erased csv and log files successfully.")
            logger.info("Erased csv and log files successfully.")



if __name__ == "__main__":
    rumps.debug_mode(True)
    frequency = 20
    iterations = 10
    debug_mode = False
    rumps.debug_mode(debug_mode)
    SpeedtestLoggerStatusBarApp(frequency=frequency, iterations=iterations).run()
