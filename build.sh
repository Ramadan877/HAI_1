#!/usr/bin/env bash
# exit on error
set -o errexit

# Install Python 3.11
python3.11 -m pip install --upgrade pip

# Install dependencies
python3.11 -m pip install -r requirements.txt