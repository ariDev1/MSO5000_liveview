"""Scope operations for the Qt interface; no Qt widgets or Tk imports here."""

import csv
import math
import os
import time
from datetime import datetime

import app.app_state as app_state
from scpi.interface import connect_scope, safe_query, safe_write, scpi_lock
from scpi.waveform import compute_power_from_scope, export_channel_csv


def channel_name(value):
    value = str(value).strip().upper()
    if value in {f"MATH{i}" for i in range(1, 5)}:
        return value
    if value.startswith("CH") and not value.startswith("CHAN"):
        value = value[2:]
    if value.startswith("CHAN"):
        value = value[4:]
    if value in {str(i) for i in range(1, 5)}:
        return f"CHAN{value}"
    raise ValueError("Select channel 1–4 or MATH1–MATH4.")


def current_scale(probe_type, probe_value, correction):
    value = float(probe_value)
    factor = float(correction)
    if not math.isfinite(value) or not math.isfinite(factor) or value <= 0 or factor <= 0:
        raise ValueError("Probe value and correction must be positive.")
    return (1 / value if probe_type == "shunt" else 1000 / value) * factor


def logging_channels(value):
    """The established logger expects analog channels as integers."""
    names = [channel_name(part) for part in value.split(",")]
    return [name if name.startswith("MATH") else int(name[4:]) for name in names]


class ScopeBackend:
    """One primary VISA handle; callers serialize tasks on a single executor."""

    def __init__(self, ip):
        self.ip = ip
        self.scope = None

    def connect(self):
        if self.scope is not None:
            self.close()
        scope = connect_scope(self.ip)
        if scope is None:
            raise ConnectionError(f"Could not connect to {self.ip}")
        self.scope = scope
        app_state.scope = scope
        app_state.scope_ip = self.ip
        with scpi_lock:
            return safe_query(scope, "*IDN?", "N/A")

    def _connected(self):
        if self.scope is None:
            raise ConnectionError("Scope is not connected.")
        return self.scope

    def snapshot(self):
        scope = self._connected()
        with scpi_lock:
            # A failed heartbeat must be visible; safe_query masks transport errors.
            try:
                scope.query("*IDN?")
            except Exception as error:
                raise ConnectionError("Scope connection lost") from error
            system = {
                "Timebase": safe_query(scope, ":TIMebase:SCALe?", "N/A"),
                "Sample rate": safe_query(scope, ":ACQuire:SRATe?", "N/A"),
                "Trigger": safe_query(scope, ":TRIGger:STATus?", "N/A"),
                "Frequency reference": safe_query(scope, ":POWer:QUALity:FREQreference?", "N/A"),
            }
            channels = {}
            for index in range(1, 5):
                name = f"CHAN{index}"
                if safe_query(scope, f":{name}:DISP?", "0") != "1":
                    continue
                channels[f"CH{index}"] = {
                    "Scale": safe_query(scope, f":{name}:SCALe?", "N/A"),
                    "Offset": safe_query(scope, f":{name}:OFFSet?", "N/A"),
                    "Coupling": safe_query(scope, f":{name}:COUPling?", "N/A"),
                    "Probe": safe_query(scope, f":{name}:PROBe?", "N/A"),
                    "Unit": safe_query(scope, f":{name}:UNIT?", "N/A"),
                }
            for index in range(1, 5):
                name = f"MATH{index}"
                if safe_query(scope, f":{name}:DISP?", "0") != "1":
                    continue
                channels[name] = {
                    "Scale": safe_query(scope, f":{name}:SCALe?", "N/A"),
                    "Offset": safe_query(scope, f":{name}:OFFSet?", "N/A"),
                    "Operator": safe_query(scope, f":{name}:OPERator?", "N/A"),
                }
        return system, channels

    def export(self, names):
        scope = self._connected()
        paths = []
        for name in names:
            path = export_channel_csv(scope, channel_name(name))
            if path is None:
                raise RuntimeError(f"Waveform export failed for {name}.")
            paths.append(path)
        return paths

    def measure(self, voltage, current, scale, remove_dc, method, raw_voltage, raw_current):
        scope = self._connected()
        result = compute_power_from_scope(
            scope, channel_name(voltage), channel_name(current),
            current_scale=scale, remove_dc=remove_dc, method=method,
            use_25m_v=raw_voltage, use_25m_i=raw_current,
        )
        if result is None:
            raise RuntimeError("No waveform data returned by scope.")
        return result

    def command(self, text):
        scope = self._connected()
        with scpi_lock:
            if "?" in text:
                return safe_query(scope, text, "(no response)")
            response = safe_write(scope, text)
            if not response:
                raise RuntimeError("SCPI write failed; see Debug Log.")
            return response

    def close(self):
        with scpi_lock:
            if self.scope is not None:
                try:
                    self.scope.close()
                finally:
                    if app_state.scope is self.scope:
                        app_state.scope = None
                    self.scope = None


class PowerLog:
    """Retain the established GUI CSV columns and sample-average semantics."""

    def __init__(self, directory="oszi_csv"):
        self.directory = directory
        self.path = None
        self.started = None
        self.count = 0
        self.totals = {name: 0.0 for name in ("P", "S", "Q", "PF", "Vrms", "Irms")}

    def add(self, result, details):
        now = time.time()
        if self.started is None:
            self.started = now
        self.count += 1
        mapping = {"P": "Real Power (P)", "S": "Apparent Power (S)",
                   "Q": "Reactive Power (Q)", "PF": "Power Factor",
                   "Vrms": "Vrms", "Irms": "Irms"}
        for key, source in mapping.items():
            self.totals[key] += float(result[source])
        average = {key: value / self.count for key, value in self.totals.items()}
        elapsed_hr = int(now - self.started) / 3600
        energy = [average[key] * elapsed_hr for key in ("P", "S", "Q")]
        if self.path is None:
            os.makedirs(self.directory, exist_ok=True)
            self.path = os.path.join(self.directory, f"power_log_{datetime.now():%Y%m%d_%H%M%S}.csv")
            with open(self.path, "w", newline="") as output:
                writer = csv.writer(output)
                writer.writerow(["# File", "Power Log"])
                for key, value in details.items():
                    writer.writerow([f"# {key}", value])
                writer.writerow(["Timestamp", "P (W)", "S (VA)", "Q (VAR)", "PF",
                                 "PF Angle (°)", "Vrms (V)", "Irms (A)",
                                 "Real Energy (Wh)", "Apparent Energy (VAh)", "Reactive Energy (VARh)"])
        with open(self.path, "a", newline="") as output:
            csv.writer(output).writerow([
                datetime.now().isoformat(), average["P"], average["S"], average["Q"],
                average["PF"], result["Phase Angle (deg)"], result["Vrms"], result["Irms"], *energy,
            ])
        return average, energy
