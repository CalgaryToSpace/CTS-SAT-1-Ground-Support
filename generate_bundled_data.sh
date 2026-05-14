#!/bin/bash

set -e

uv run cts1_ground_support/firmware_config_variable_parser.py  ../CTS-SAT-1-OBC-Firmware/ | tee cts1_ground_support/bundled_data/cts_sat_1_config_variable_list.json
uv run cts1_ground_support/telecommand_array_parser.py ../CTS-SAT-1-OBC-Firmware/ | tee cts1_ground_support/bundled_data/cts_sat_1_telecommand_list.json
