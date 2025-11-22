#!/usr/bin/env python3
"""
Dedicated Voltage Monitor and Shutdown Script
"""
import time
import os
import subprocess
import sys

# Voltage monitoring
try:
    import board
    import busio
    import adafruit_ads1x15.ads1015 as ADS
    from adafruit_ads1x15.analog_in import AnalogIn
    ADC_AVAILABLE = True
except ImportError:
    ADC_AVAILABLE = False
    print("ADC libraries not found")

# Configuration
VOLTAGE_THRESHOLD = 11.5  # Shutdown below this
VOLTAGE_GRACE_PERIOD = 30  # Seconds to wait before shutdown
CHECK_INTERVAL = 5  # Seconds

def read_voltage(adc_chan):
    if not adc_chan:
        return 12.5 # Mock
    try:
        # Voltage divider: 3.3V max input. 
        # Assuming standard PiCAN divider or similar.
        # Adjust multiplier as needed for your specific hardware divider.
        # PiCAN3 usually uses 1/3 divider or similar? 
        # Actually PiCAN3 manual says: "The voltage is readable via the bridge on GPIO26... No, that's for something else."
        # PiCAN3 has a SMPS. 
        # If using an external ADS1115, the multiplier depends on the resistors.
        # The previous script used: self.adc_chan.voltage * 2 * 3.3 / 2047.0 ??
        # Let's stick to a generic multiplier or the one from the previous script.
        # Previous: self.adc_chan.voltage * 2 * 3.3 / 2047.0  <-- This looks like a raw value conversion?
        # ADS1015 raw is 12-bit (0-2047). 
        # Let's use the voltage property directly which gives Volts.
        return adc_chan.voltage * 3.0 # Example multiplier, user needs to calibrate
    except Exception as e:
        print(f"Error reading voltage: {e}")
        return 0.0

def shutdown():
    print("Initiating shutdown...")
    sys.stdout.flush()
    try:
        # Use nsenter to execute shutdown on the host (pid 1 namespace)
        # This requires the container to be privileged and running as root
        subprocess.run(
            ['nsenter', '--target', '1', '--mount', '--uts', '--ipc', '--net', '--pid', '--', 'shutdown', '-h', 'now'], 
            check=True
        )
    except Exception as e:
        print(f"Shutdown failed: {e}")
        # Fallback: Try SysRq trigger (hard power off)
        try:
            with open('/proc/sysrq-trigger', 'w') as f:
                f.write('o')
        except Exception as e2:
            print(f"SysRq fallback failed: {e2}")

def main():
    if not ADC_AVAILABLE:
        print("No ADC available, voltage monitor disabled.")
        while True:
            time.sleep(60)

    i2c = busio.I2C(board.SCL, board.SDA)
    ads = ADS.ADS1015(i2c)
    chan = AnalogIn(ads, ADS.P0)
    
    low_voltage_start = None

    print(f"Voltage monitor started. Threshold: {VOLTAGE_THRESHOLD}V")

    while True:
        voltage = read_voltage(chan)
        print(f"Voltage: {voltage:.2f}V")
        
        if voltage < VOLTAGE_THRESHOLD:
            if low_voltage_start is None:
                low_voltage_start = time.time()
                print(f"Low voltage detected! Timer started.")
            elif time.time() - low_voltage_start > VOLTAGE_GRACE_PERIOD:
                print(f"Low voltage persisted for {VOLTAGE_GRACE_PERIOD}s. Shutting down.")
                shutdown()
        else:
            if low_voltage_start is not None:
                print("Voltage recovered.")
            low_voltage_start = None
            
        sys.stdout.flush()
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
