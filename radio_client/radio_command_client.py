#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# client library implementing commands for the ettus radios to be sent via zmq socket

import os
import time
from datetime import datetime, timezone
from threading import Thread
import multiprocessing
import zmq
import pmt

class RadioZmqClient:
    def __init__(self, sub_port=5562, pub_port=5563):
        """ Instantiate zmq sources and sinks to talk to the radio and make 
        life a bit easier for writing other programs. Currently this is 
        specifically for westford and campus L band

        note that this all assumes the radio clock is more or less correctly synced to utc"""

        self.gpio_state = 0
        self.gpio_bank = 'FP0A'
        self.gpio_attr = 'OUT'
        self.gpio_mask = 0b11

        #create zmq message contexts

        #ZMQ sub

        self.context = zmq.Context()
        self.sub_socket = self.context.socket(zmq.SUB)
        self.sub_socket.connect("tcp://localhost:%s" % sub_port)
        self.sub_socket.subscribe("")

        #ZMQ pub

        self.pub_socket = self.context.socket(zmq.PUB)
        self.pub_socket.bind("tcp://*:%s" % pub_port)


    def get_message(self):
        """Get message from zmq sub"""
        message = self.sub_socket.recv()
        return pmt.to_python(pmt.deserialize_str(message))

    def send_message(self, message ):
        """send a message via zmq pub"""
        self.pub_socket.send(pmt.serialize_str(message)) 

    def set_command_timestamp(self, timestamp):
        """set command execution time based on a unix timestamp"""
        command_time = pmt.cons(pmt.from_uint64(int(timestamp)),pmt.from_double(timestamp - int(timestamp)))
        msg = pmt.make_dict()
        msg = pmt.dict_add(msg, pmt.to_pmt('time'), command_time)
        self.send_message(msg)

    def set_command_time(self, isotime):
        """set command execution time based on iso time"""
        command_time = datetime.fromisoformat(isotime).timestamp()
        self.set_command_timestamp(command_time)

    def clear_command_time(self):
        """clear timed command flag"""
        msg = pmt.make_dict()
        msg = pmt.dict_add(msg, pmt.to_pmt('time'), pmt.PMT_NIL)
        self.send_message(msg)

    def set_gpio_mask(self, mask):
        """set the default GPIO Mask for set_gpio_state command"""
        self.gpio_mask = mask

    def set_gpio_attr(self, attr):
        """set the default GPIO attr for set_gpio_state command"""
        self.gpio_attr = attr

    def set_gpio_bank(self, bank):
        """set the default GPIO bank for set_gpio_state command"""
        self.gpio_bank = bank

    def set_gpio_state(self, gpio_values):
        """set GPIO outputs on radio
        this is somewhat convoluted as implemented 
        because need to send a dictionary to tell 
        the radio everything we need to""" 
        
        self.set_gpio_attr(self.gpio_bank, self.gpio_attr, gpio_values, self.gpio_mask)


    def set_gpio_attr(self, bank, attr, value, mask):
        """
        full access to set_gpio_attr command in UHD
        see https://files.ettus.com/manual/page_gpio_api.html,
        usrp block source https://github.com/gnuradio/gnuradio/blob/main/gr-uhd/lib/usrp_block_impl.cc#L705
        and uhd documentation, other than that this is extremely badly documented.

        Inputs:
            bank: str() 
                GPIO BANK
            attr: str() 
                GPIO Attribute
            value: int  
                value to set gpio register
            mask: int
                which bits in register should we actually change

        form is

        set_gpio_attr(bank, attr, value, bitmask)

        Example: commands to setup pins 2 and 3 (data 0 and 1) as output on an X310 are

        set_gpio_attr( 'FP0A', 'CTRL', 0x000, 0b11) 
        sets ATR control to zero for lowest 2 bits (manual control)

        set_gpio_attr( 'FP0A', 'DDR', 0xFFF, 0b11) 
        sets lowest two bits in register as output (1 for output)

        set_gpio_attr( 'FP0A', 'OUT', 0x000, 0b11) 
        sets outputs to zero

        """

        set_gpio = pmt.make_dict()
        set_gpio = pmt.dict_add(set_gpio, pmt.to_pmt('bank'), pmt.to_pmt(bank))
        set_gpio = pmt.dict_add(set_gpio, pmt.to_pmt('attr'), pmt.to_pmt(attr))
        set_gpio = pmt.dict_add(set_gpio, pmt.to_pmt('value'), pmt.from_double(value))
        set_gpio = pmt.dict_add(set_gpio, pmt.to_pmt('mask'), pmt.from_double(mask))

        msg = pmt.make_dict()
        msg = pmt.dict_add(msg, pmt.to_pmt('gpio'), set_gpio)

        self.send_message(msg)
        
if __name__ == '__main__':
    radio = RadioZmqClient(sub_port=5562, pub_port=5563)