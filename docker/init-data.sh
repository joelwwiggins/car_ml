#!/bin/bash

# Wait for VictoriaMetrics to be ready
sleep 10

# Push sample OBD2 metrics data (simulating training data)
curl -X POST http://victoriametrics:8428/api/v1/import/prometheus -d "
obd2_engine_rpm{vehicle=\"sample\"} 2500 $(date +%s)000
obd2_vehicle_speed{vehicle=\"sample\"} 60 $(date +%s)000
obd2_engine_rpm{vehicle=\"sample\"} 2800 $(($(date +%s) - 60))000
obd2_vehicle_speed{vehicle=\"sample\"} 65 $(($(date +%s) - 60))000
obd2_engine_rpm{vehicle=\"sample\"} 2200 $(($(date +%s) - 120))000
obd2_vehicle_speed{vehicle=\"sample\"} 55 $(($(date +%s) - 120))000
"