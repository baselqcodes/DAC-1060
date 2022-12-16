import numpy
import qcodes
import pyvisa as visa
import socket
from qcodes.dataset.measurements import Measurement
from qcodes.dataset.plotting import plot_dataset
from qcodes.instrument_drivers.Keysight.Keysight_34465A_submodules import Keysight_34465A

from qcodes import logger
from SP1060_24_AWG import SP1060 # DAC
logger.start_all_logging
dac = SP1060('LNHR_dac', "TCPIP0::192.168.0.5::23::SOCKET")
# import inspect
# print(inspect.getmro(type(dac)))
#print('Current DAC output: ' +  str(dac.channels[:].volt.get()))
dac.ch12.volt(3)
print('Current DAC output: ' +  str(dac.channels[:].volt.get()))

