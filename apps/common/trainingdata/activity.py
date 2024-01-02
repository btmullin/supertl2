from dataclasses import dataclass, field
from datetime import date, timedelta, time, datetime
from typing import List, Tuple
import os
from garmin_fit_sdk import Decoder, Stream
import trainingdata.gpsutils as GPSUtils
import pandas as pd

@dataclass
class ActivitySummary:
    title: str = "Untitled Workout"
    start: datetime = datetime.now()
    distance_m: float = 0.0
    active_duration_s: float = 0.0
    elapsed_duration: float = 0.0
    elevation_m: float = 0.0
    avg_speed_mps: float = 0.0

    def __init__(self, source_file: str) -> None:
        # determine file type
        extension = os.path.splitext(source_file)[1]

        match extension:
            case '.fit':
                # open a fit file
                self.import_fit(source_file)

            case '.gpx':
                # open a gpx file
                self.import_gpx(source_file)
        
            case _:
                # unknown file type
                # benbug raise error
                pass

    def import_fit(self, source_file: str) -> None:
        stream = Stream.from_file(source_file)
        decoder = Decoder(stream)
        messages, errors = decoder.read()

        session_data = messages['session_mesgs'][0]
        self.start = session_data['start_time']
        self.distance_m = session_data['total_distance']
        self.active_duration_s = session_data['total_timer_time']
        self.elapsed_duration_s = session_data['total_elapsed_time']
        self.elevation_m = session_data['total_ascent']
        self.avg_speed_mps = session_data['enhanced_avg_speed']

    def import_gpx(self, source_file: str) -> None:
        # benbug - implement gpx import
        pass

    def get_active_time(self) -> str:
        return str(timedelta(seconds=self.active_duration_s)).split('.')[0]

# benbug - where does this belong
OPTIONAL_FIT_RECORDS = ["enhanced_altitude", "position_lat", "position_long", "enhanced_speed", "fractional_cadence", "heart_rate", "distance"]

@dataclass
class GPSActivityData:
    # laps
    # power
    source_file = ''
    activity_hash = 0
    start: datetime = None
    time_series_data: pd.DataFrame = None

    def __init__(self, source_file: str) -> None:
        self.source_file = source_file
        self.time_series_data = pd.DataFrame()
        # determine file type
        extension = os.path.splitext(source_file)[1]

        match extension:
            case '.fit':
                # open a fit file
                self.import_fit(source_file)

            case '.gpx':
                # open a gpx file
                self.import_gpx(source_file)
        
            case _:
                # unknown file type
                # benbug raise error
                pass

    def import_fit(self, source_file: str) -> None:
        stream = Stream.from_file(source_file)
        decoder = Decoder(stream)
        messages, errors = decoder.read()

        for rec in messages["record_mesgs"]:
            # for each key that exists in record and is in OPTIONAL_FIT_RECORDS
            # add it to a dictionary
            series_row = {}
            series_row.update({"timestamp":rec["timestamp"]})

            rec_keys = rec.keys()

            data_keys = [k for k in OPTIONAL_FIT_RECORDS if k in rec.keys()]

            for key in data_keys:
                series_row.update({key:[rec[key]]})

            # turn the dictionary into a dataframe and append it to the existing data
            self.time_series_data = pd.concat([self.time_series_data,
                                               pd.DataFrame.from_dict(series_row)],
                                              ignore_index=True)

        # Global transformations post parsing
        # conversion from semicircles to degrees
        self.time_series_data["position_lat"] = self.time_series_data["position_lat"].apply(GPSUtils.semicircles_to_degrees)
        self.time_series_data["position_long"] = self.time_series_data["position_long"].apply(GPSUtils.semicircles_to_degrees)

        # benbug - parse summary information
        session_data = messages["session_mesgs"][0]
        self.start = session_data['start_time']

    def import_gpx(self, source_file: str) -> None:
        # benbug - implement gpx import
        pass

@dataclass
class Activity:
    summary: ActivitySummary = field(default_factory=ActivitySummary)
    gps_data: GPSActivityData = None
    source_file: str = ''

    def __init__(self, source_file: str) -> None:
        self.source_file = source_file
        self.gps_data = GPSActivityData(self.source_file)
        self.summary = ActivitySummary(self.source_file)

        # benbug - get the summary information
