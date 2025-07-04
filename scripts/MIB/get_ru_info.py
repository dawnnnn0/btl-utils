#!/usr/bin/env python3

import python.constants as constants
import python.utils as utils

utils.save_all_part_info(
    parttype = constants.RU.KIND_OF_PART,
    outyamlfile = "info/MIB/ru_info.yaml",
    inyamlfile = "info/MIB/ru_info.yaml",
    location_id = [constants.LOCATION.MIB, constants.LOCATION.CERN],
    ret = False
)
