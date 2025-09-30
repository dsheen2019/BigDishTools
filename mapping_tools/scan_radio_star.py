#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# dsheen 2025/09/30
# perform a grid scan of a radio star and log position data



import os
import sys
import digital_rf as drf
from datetime import datetime, timezone
import time
import argparse
import csv
import time

from radio_command_client import RadioZmqClient
from bigdish_client import BigDishClient