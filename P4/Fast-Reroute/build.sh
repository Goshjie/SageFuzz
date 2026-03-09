#!/bin/bash

# Exit on any error
set -e

# Define directories and files
SOURCE_DIR="p4src"
BUILD_DIR="build"
GRAPHS_DIR="${BUILD_DIR}/graphs"
P4_PROGRAM="fast_reroute.p4"
JSON_OUTPUT="${BUILD_DIR}/fast_reroute.json"
P4INFO_OUTPUT="${BUILD_DIR}/fast_reroute.p4.p4info.txt"

# Create build directories if they don't exist
echo "Creating build directories..."
mkdir -p "${GRAPHS_DIR}"

# Compile P4 program to BMv2 JSON and P4Info
echo "Compiling ${P4_PROGRAM}..."
p4c-bm2-ss --p4v 16 \
    --p4runtime-files "${P4INFO_OUTPUT}" \
    -o "${JSON_OUTPUT}" \
    "${SOURCE_DIR}/${P4_PROGRAM}"

# Generate DOT graphs
echo "Generating control flow graphs..."
p4c-graphs --p4v 16 \
    --graphs-dir "${GRAPHS_DIR}" \
    "${SOURCE_DIR}/${P4_PROGRAM}"

echo "Build complete! Artifacts are in ${BUILD_DIR}/"
ls -F "${BUILD_DIR}" "${GRAPHS_DIR}"
