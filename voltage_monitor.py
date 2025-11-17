#!/usr/bin/env python3
"""
Standalone Voltage Monitor for Raspberry Pi Zero 2W
Monitors battery voltage and triggers system shutdown when below threshold.
Designed to run as a systemd service or cron job.
"""

import time
import logging
import sys
import os
import subprocess
from typing import Optional

# Adafruit libraries for ADC
try:
    import board
    import busio
    import adafruit_ads1x15.ads1015 as ADS
    from adafruit_ads1x15.analog_in import AnalogIn
    ADC_AVAILABLE = True
except ImportError:
    ADC_AVAILABLE = False

# Configuration
VOLTAGE_THRESHOLD = 11.0  # Volts - shutdown threshold
CHECK_INTERVAL = 30  # Seconds between checks
GRACE_PERIOD = 60  # Seconds to wait before shutdown after low voltage detected
LOG_FILE = '/var/log/voltage_monitor.log'
SHUTDOWN_COMMAND = ['sudo', 'shutdown', '-h', 'now']

class VoltageMonitor:
    def __init__(self):
        self.logger = self._setup_logging()
        self.ads: Optional[ADS.ADS1015] = None
        self.chan: Optional[AnalogIn] = None
        self.low_voltage_start: Optional[float] = None

        if ADC_AVAILABLE:
            self._setup_adc()
        else:
            self.logger.warning("ADC libraries not available, using mock voltage")

    def _setup_logging(self) -> logging.Logger:
        """Setup logging for voltage monitoring."""
        logger = logging.getLogger('voltage_monitor')
        logger.setLevel(logging.INFO)

        # Ensure log directory exists
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

        # File handler
        file_handler = logging.FileHandler(LOG_FILE)
        file_handler.setLevel(logging.INFO)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)

        # Formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

        return logger

    def _setup_adc(self):
        """Setup ADS1015 ADC for voltage monitoring."""
        try:
            # Initialize I2C bus and ADC
            i2c = busio.I2C(board.SCL, board.SDA)
            self.ads = ADS.ADS1015(i2c)
            self.chan = AnalogIn(self.ads, ADS.P0)  # A0 pin

            self.logger.info("ADS1015 ADC initialized successfully")
        except Exception as e:
            self.logger.error(f"Failed to initialize ADC: {e}")
            ADC_AVAILABLE = False

    def read_voltage(self) -> float:
        """Read battery voltage from ADC."""
        if self.chan and ADC_AVAILABLE:
            try:
                # Voltage divider calculation
                # Assuming 10k/10k divider (half voltage)
                # ADC reading * 2 * reference voltage / max ADC value
                raw_voltage = self.chan.voltage
                battery_voltage = raw_voltage * 2 * 3.3 / 2047.0

                self.logger.debug(f"Raw ADC: {raw_voltage:.3f}V, Battery: {battery_voltage:.1f}V")
                return battery_voltage

            except Exception as e:
                self.logger.error(f"Error reading ADC: {e}")
                return self._mock_voltage()
        else:
            return self._mock_voltage()

    def _mock_voltage(self) -> float:
        """Return mock voltage for testing without hardware."""
        # Simulate realistic voltage levels
        import random
        base_voltage = 12.5
        variation = random.uniform(-0.5, 0.5)
        voltage = base_voltage + variation
        self.logger.debug(f"Mock voltage: {voltage:.1f}V")
        return voltage

    def check_voltage_and_shutdown(self):
        """Check voltage and initiate shutdown if below threshold."""
        voltage = self.read_voltage()

        if voltage < VOLTAGE_THRESHOLD:
            current_time = time.time()

            if self.low_voltage_start is None:
                # First detection of low voltage
                self.low_voltage_start = current_time
                self.logger.warning(f"Low voltage detected: {voltage:.1f}V (threshold: {VOLTAGE_THRESHOLD}V)")
                self.logger.info(f"Waiting {GRACE_PERIOD} seconds before shutdown...")
                return False

            elif current_time - self.low_voltage_start >= GRACE_PERIOD:
                # Low voltage persisted for grace period
                self.logger.critical(f"Low voltage persisted for {GRACE_PERIOD}s. Voltage: {voltage:.1f}V. Initiating shutdown.")
                self._shutdown_system()
                return True

            else:
                # Still in grace period
                remaining = int(GRACE_PERIOD - (current_time - self.low_voltage_start))
                self.logger.warning(f"Low voltage persists: {voltage:.1f}V. Shutdown in {remaining}s")
                return False

        else:
            # Voltage is normal
            if self.low_voltage_start is not None:
                self.logger.info(f"Voltage recovered to {voltage:.1f}V")
                self.low_voltage_start = None
            return False

    def _shutdown_system(self):
        """Execute system shutdown."""
        try:
            self.logger.info("Executing shutdown command...")
            result = subprocess.run(SHUTDOWN_COMMAND, capture_output=True, text=True)

            if result.returncode == 0:
                self.logger.info("Shutdown command executed successfully")
            else:
                self.logger.error(f"Shutdown command failed: {result.stderr}")

        except Exception as e:
            self.logger.error(f"Failed to execute shutdown: {e}")

    def run_continuous_monitoring(self):
        """Run continuous voltage monitoring."""
        self.logger.info(f"Starting voltage monitor (threshold: {VOLTAGE_THRESHOLD}V, interval: {CHECK_INTERVAL}s)")

        try:
            while True:
                if self.check_voltage_and_shutdown():
                    # Shutdown initiated, exit loop
                    break

                time.sleep(CHECK_INTERVAL)

        except KeyboardInterrupt:
            self.logger.info("Received interrupt signal, stopping monitor")
        except Exception as e:
            self.logger.error(f"Unexpected error in monitoring loop: {e}")

def main():
    """Main entry point."""
    monitor = VoltageMonitor()
    monitor.run_continuous_monitoring()

if __name__ == "__main__":
    main()