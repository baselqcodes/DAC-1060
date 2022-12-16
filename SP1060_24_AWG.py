from typing import Optional, Sequence, Dict, Tuple, Any, Union, List
import time
import pyvisa as visa
import logging
from functools import partial
from qcodes import VisaInstrument, InstrumentChannel, ChannelList
from qcodes.instrument.channel import MultiChannelInstrumentParameter
from qcodes.utils import validators as vals
log = logging.getLogger(__name__)

class SP1060Exception(Exception):
    pass


class SP1060Reader(object):
    def _vval_to_dacval(self, vval):
        """
        Convert voltage to DAC value 
        dacval=(Vout+10)*838860.75 
        """
        try:
            dacval = int((float(vval)+10)*838860.75 )
            return dacval
        except:
            pass

    def _dacval_to_vval(self, dacval):
        """
        Convert DAC value to voltage
        Vout=(dacval/838860.75 )–10
        """
        try:
            vval = round((int(dacval.strip(),16)/float(838860.75))-10, 6)
            return vval
        except:
            pass


class SP1060MultiChannel(MultiChannelInstrumentParameter, SP1060Reader):
    def __init__(self, channels:Sequence[InstrumentChannel], param_name: str, *args: Any, **kwargs: Any):
        super().__init__(channels, param_name, *args, **kwargs)
        self._channels = channels
        self._param_name = param_name
        
        def get_raw(self):
            output = tuple(chan.parameters[self._param_name].get() for chan in self._channels)
            return output
        
        def set_raw(self, value):
            for chan in self._channels:
                chan.volt.set(value)
            
    
class SP1060Channel(InstrumentChannel, SP1060Reader):
   
    def __init__(self, parent, name, channel, min_val=-10, max_val=10):
        super().__init__(parent, name)
        
        # validate channel number
        self._CHANNEL_VAL = vals.Ints(1,24)
        self._CHANNEL_VAL.validate(channel)
        self._channel = channel

        # limit voltage range
        self._volt_val = vals.Numbers(min(min_val, max_val), max(min_val, max_val))
        
        self.add_parameter('volt',
                           label = 'C {}'.format(channel),
                           unit = 'V',
                           set_cmd = partial(self._parent._set_voltage, channel),
                           set_parser = self._vval_to_dacval,
                           get_cmd = partial(self._parent._read_voltage, channel),
                           vals = self._volt_val 
                           )

class SP1060(VisaInstrument, SP1060Reader):
    """
    QCoDeS driver for the Basel Precision Instruments SP1060 LNHR DAC
    https://www.baspi.ch/low-noise-high-resolution-dac
    """
    
    def __init__(self, name, address, min_val=-10, max_val=10, baud_rate=115200, **kwargs):
        """
        Creates an instance of the SP1060 24 channel LNHR DAC instrument.

        Args:
            name (str): What this instrument is called locally.

            port (str): The address of the DAC. For a serial port this is ASRLn::INSTR
                        where n is replaced with the address set in the VISA control panel.
                        Baud rate and other serial parameters must also be set in the VISA control
                        panel.

            min_val (number): The minimum value in volts that can be output by the DAC.
            max_val (number): The maximum value in volts that can be output by the DAC.
        """
        super().__init__(name, address, **kwargs)

        # Serial port properties
        handle = self.visa_handle
        handle.baud_rate = baud_rate
        handle.parity = visa.constants.Parity.none
        handle.stop_bits = visa.constants.StopBits.one
        handle.data_bits = 8
        handle.flow_control = visa.constants.VI_ASRL_FLOW_XON_XOFF
        handle.write_termination = '\r\n'
        handle.read_termination = '\r\n'

        # Create channels
        channels = ChannelList(self, 
                               "Channels", 
                               SP1060Channel, 
                               snapshotable = False,
                               multichan_paramclass = SP1060MultiChannel)
        self.num_chans = 24
        
        for i in range(1, 1+self.num_chans):
            channel = SP1060Channel(self, 'chan{:1}'.format(i), i)
            channels.append(channel)
            self.add_submodule('ch{:1}'.format(i), channel)
        channels.lock()
        self.add_submodule('channels', channels)

        # Safety limits for sweeping DAC voltages
        # inter_delay: Minimum time (in seconds) between successive sets.
        #              If the previous set was less than this, it will wait until the
        #              condition is met. Can be set to 0 to go maximum speed with
        #              no errors.    
         
        # step: max increment of parameter value.
        #       Larger changes are broken into multiple steps this size.
        #       When combined with delays, this acts as a ramp.
        for chan in self.channels:
            chan.volt.inter_delay = 0.02
            chan.volt.step = 0.01
        
        # switch all channels ON if still OFF
        if 'OFF' in self.query_all():
            self.all_on()
            
        self.connect_message()
        print('Current DAC output: ' +  str(self.channels[:].volt.get()))

    def _set_voltage(self, chan, code):
        self.write('{:0} {:X}'.format(chan, code))
            
    def _read_voltage(self, chan):
        dac_code=self.write('{:0} V?'.format(chan))
        return self._dacval_to_vval(dac_code)

    def set_all(self, volt):
        """
        Set all dac channels to a specific voltage.
        """
        for chan in self.channels:
            chan.volt.set(volt)
    
    def query_all(self):
        """
        Query status of all DAC channels
        """
        reply = self.write('All S?')
        return reply.replace("\r\n","").split(';')
    
    def all_on(self):
        """
        Turn on all channels.
        """
        self.write('ALL ON')
      
    def all_off(self):
        """
        Turn off all channels.
        """
        self.write('ALL OFF')
    
    def empty_buffer(self):
        # make sure every reply was read from the DAC 
       # while self.visa_handle.bytes_in_buffer:
       #     print(self.visa_handle.bytes_in_buffer)
       #     print("Unread bytes in the buffer of DAC SP1060 have been found. Reading the buffer ...")
       #     print(self.visa_handle.read_raw())
       #      self.visa_handle.read_raw()
       #     print("... done")
        self.visa_handle.clear() 
          
    def write(self, cmd):
        """
        Since there is always a return code from the instrument, we use ask instead of write
        TODO: interpret the return code (0: no error)
        """
        # make sure there is nothing in the buffer
        self.empty_buffer()  
        
        return self.ask(cmd)
    
    def get_serial(self):
        """
        Returns the serial number of the device
        Note that when querying "HARD?" multiple statements, each terminated
        by \r\n are returned, i.e. the device`s reply is not terminated with 
        the first \n received

        """
        self.write('HARD?')
        reply = self.visa_handle.read()
        time.sleep(0.01)
       # while self.visa_handle.bytes_in_buffer:
       #     self.visa_handle.read_raw()
       #     time.sleep(0.01)
        self.empty_buffer()
        return reply.strip()[3:]
    
    def get_firmware(self):
        """
        Returns the firmware of the device
        Note that when querying "HARD?" multiple statements, each terminated
        by \r\n are returned, i.e. the device`s reply is not terminated with 
        the first \n received

        """
        self.write('SOFT?')
        reply = self.visa_handle.read()
        time.sleep(0.01)
       # while self.visa_handle.bytes_in_buffer:
       #     self.visa_handle.read_raw()
       #     time.sleep(0.01)
        self.empty_buffer()
        return reply.strip()[-5:]
        
    
    def get_idn(self):
        SN = self.get_serial()
        FW = self.get_firmware()
        return dict(zip(('vendor', 'model', 'serial', 'firmware'), 
                        ('BasPI', 'LNHR DAC SP1060', SN, FW)))
                        

    def set_newWaveform(self, channel = '12', waveform = '0', frequency = '100.0', 
                        amplitude = '5.0', wavemem = '0'):
        """
        Write the Standard Waveform Function to be generated
        - Channel: [1 ... 24]
        Note: AWG-A and AWG-B only DAC-Channel[1...12], AWG-C and AWG-D only DAC-Channel[13...24]
        - Waveforms: 
            0 = Sine function, for a Cosine function select a Phase [°] of 90°
            1 = Triangle function
            2 = Sawtooth function
            3 = Ramp function
            4 = Pulse function, the parameter Duty-Cycle is applied
            5 = Gaussian Noise (Fixed), always the same seed for the random/noise-generator
            6 = Gaussian Noise (Random), random seed for the random/noise-generator
            7 = DC-Voltage only, a fixed voltage is generated
        - Frequency: AWG-Frequency [0.001 ... 10.000]
        - Amplitude: [-50.000000 ... 50.000000]
        - Wave-Memory (WAV-A/B/C/D) are represented by 0/1/2/3 respectively
        """
        memsave = ''
        if (wavemem == '0'):
            memsave = 'A'
        elif (wavemem == '1'):
            memsave = 'B'
        elif (wavemem == '2'):
            memsave = 'C'
        elif (wavemem == '3'):
            memsave = 'D'

        self.write('C WAV-B CLR') # Wave-Memory Clear.
        time.sleep(0.01)
        self.write('C SWG MODE 0') # generate new Waveform.
        time.sleep(0.01)
        self.write('C SWG WF ' + waveform) # set the waveform.
        time.sleep(0.01)
        self.write('C SWG DF ' + frequency) # set frequency.
        time.sleep(0.01)
        self.write('C SWG AMP ' + amplitude) # set the amplitude.
        time.sleep(0.01)
        self.write('C SWG WMEM ' + wavemem) # set the Wave-Memory.
        time.sleep(0.01)
        self.write('C SWG WFUN 0') # COPY to Wave-MEM -> Overwrite.
        time.sleep(0.01)
        self.write('C SWG LIN ' + channel) # COPY to Wave-MEM -> Overwrite.
        time.sleep(0.01)
        self.write('C AWG-' + memsave + ' CH ' + channel) # Write the Selected DAC-Channel for the AWG.
        time.sleep(0.01)
        self.write('C SWG APPLY') # Apply Wave-Function to Wave-Memory Now.
        time.sleep(0.01)
        self.write('C WAV-' + memsave + ' SAVE') # Save the selected Wave-Memory (WAV-A/B/C/D) to the internal volatile memory.
        time.sleep(0.01)
        self.write('C WAV-' + memsave + ' WRITE') # Write the Wave-Memory (WAV-A/B/C/D) to the corresponding AWG-Memory (AWG-A/B/C/D).
        time.sleep(0.01)
        self.write('C AWG-' + memsave + ' START') # Apply Wave-Function to Wave-Memory Now.

if __name__ == '__main__':    
    dac = SP1060('LNHR_dac3', 'TCPIP0::192.168.0.5::23::SOCKET')
    dac.set_newWaveform('12','0','100.0','5.0','0') # sinewave
    #dac.set_newWaveform('12','1','100.0','5.0','0') # triangle
    dac.close()
