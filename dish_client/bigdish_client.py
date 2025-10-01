#!/usr/bin/env python3

import time
import json
import threading
from websockets.sync.client import connect

class BigDishClient:
    def __init__(self, server_host, server_port):
        '''
        get to CONNECTED state only. 

        User must then authenticate to authenticated state, and request dish control using initialize_connection
        '''

        self.websocket = connect(f"ws://{server_host}:{server_port}")

        self.message_id = 0
        self.received_messages = {}
        self._message_recv_thread_handle = threading.Thread(target = self._message_recv_thread)
        self._message_recv_thread_handle.start()

    def _message_recv_thread(self):
        for message in self.websocket:
            message_decoded = json.loads(message)
            self.received_messages[message_decoded["id"]] = message_decoded

    def _wait_for_response(self, id):
        while True:
            if id in self.received_messages:
                message = self.received_messages[id]
                del self.received_messages[id]
                self.message_id += 1
                return message
            time.sleep(0.01)

    def authenticate_connection(self, user, password):
        self.websocket.send(json.dumps({"type": "auth", "id": self.message_id, "user": user, "password": password, "version": "0.1.0"}))
        return self._wait_for_response(self.message_id)

    def initialize_connection(self, kick_others=False):
        '''
        escalate to INITIALIZED state so we can control the dish.
        '''
        self.websocket.send(json.dumps({"type": "init", "id": self.message_id, "kick_others": kick_others}))
        return self._wait_for_response(self.message_id)

    def get_connections(self):
        self.websocket.send(json.dumps({"type": "get_connections", "id": self.message_id}))
        return self._wait_for_response(self.message_id)

    def get_active_users(self):
        self.websocket.send(json.dumps({"type": "get_active_users", "id": self.message_id}))
        return self._wait_for_response(self.message_id)

    def get_active_movement_command(self):
        self.websocket.send(json.dumps({"type": "get_active_movement_command", "id": self.message_id}))
        return self._wait_for_response(self.message_id)

    def get_offset(self):
        '''
        get the offset corrections currently applied by the dish control 
        loop when communicating with the motor controllers
        '''
        self.websocket.send(json.dumps({"type": "get_offset", "id": self.message_id}))
        return self._wait_for_response(self.message_id)

    def set_offset(self, az_offset, el_offset):
        '''
        program correctior for dish pointing errors or for feed offsets
        NOTE: This is not intended for use for offset tracking. 
        please add offsets to your commands in your own code if you need that

        when you SHOULD use this is if you have a feed with a known squint 
        off of boresight and want the dish controller to treat that as the new boresight angle.

        this is reset upon a new client connecting and will persist across multiple sessions, so it can't break anything
        '''
        self.websocket.send(json.dumps({"type": "set_offset", "az_offset" : az_offset, "el_offset" : el_offset, "id": self.message_id}))
        return self._wait_for_response(self.message_id)

    def stow_pos(self):
        self.websocket.send(json.dumps({"type": "stow_pos", "id": self.message_id}))
        return self._wait_for_response(self.message_id)

    def service_pos(self):
        self.websocket.send(json.dumps({"type": "service_pos", "id": self.message_id}))
        return self._wait_for_response(self.message_id)

    def goto_posvel(self, coords, coord1, coord2, vel1, vel2, executeat=None):
        #single handler for all posvel types 
        if coords == "azel":
            return(self.goto_posvel_azel(coord1, coord2, vel1, vel2, executeat=executeat))
        elif coords == "radec":
            return(self.goto_posvel_radec(coord1, coord2, vel1, vel2, executeat=executeat))
        elif coords == "gal":
            return(self.goto_posvel_gal(coord1, coord2, vel1, vel2, executeat=executeat))
        else:
            return(f"Bad Command Coordinate System! {coords} is not a recognized coordinate system")

    def goto_posvel_azel(self, az_pos, el_pos, az_vel, el_vel, executeat=None):
        if executeat is not None:
            self.websocket.send(json.dumps({"type": "goto_posvel", "id": self.message_id, "coords": "azel", "executeat": executeat, "az_pos": az_pos, "az_vel": az_vel, "el_pos": el_pos, "el_vel": el_vel}))
        else:
            self.websocket.send(json.dumps({"type": "goto_posvel", "id": self.message_id, "coords": "azel", "az_pos": az_pos, "az_vel": az_vel, "el_pos": el_pos, "el_vel": el_vel}))
        return self._wait_for_response(self.message_id)

    def goto_posvel_radec(self, ra_pos, dec_pos, ra_vel, dec_vel, executeat=None):
        if executeat is not None:
            self.websocket.send(json.dumps({"type": "goto_posvel", "id": self.message_id, "coords": "radec", "executeat": executeat, "ra_pos": ra_pos, "ra_vel": ra_vel, "dec_pos": dec_pos, "dec_vel": dec_vel}))
        else:
            self.websocket.send(json.dumps({"type": "goto_posvel", "id": self.message_id, "coords": "radec", "ra_pos": ra_pos, "ra_vel": ra_vel, "dec_pos": dec_pos, "dec_vel": dec_vel}))
        return self._wait_for_response(self.message_id)

    def goto_posvel_gal(self, l_pos, b_pos, l_vel, b_vel, executeat=None):
        if executeat is not None:
            self.websocket.send(json.dumps({"type": "goto_posvel", "id": self.message_id, "coords": "gal", "executeat": executeat, "l_pos": l_pos, "l_vel": l_vel, "b_pos": b_pos, "b_vel": b_vel}))
        else:
            self.websocket.send(json.dumps({"type": "goto_posvel", "id": self.message_id, "coords": "gal", "l_pos": l_pos, "l_vel": l_vel, "b_pos": b_pos, "b_vel": b_vel}))
        return self._wait_for_response(self.message_id)

    def track(self, coords, coord1, coord2, vel1=0.0, vel2=0.0, duration=1, executeat=None):
        #function for all track command types
        if coords == "azel":
            return(self.track_azel(coord1, coord2, az_vel=vel1, el_vel=vel2, duration=duration, executeat=executeat))
        elif coords == "radec":
            return(self.track_radec(coord1, coord2, ra_vel=vel1, dec_vel=vel2, duration=duration, executeat=executeat))
        elif coords == "gal":
            return(self.track_gal(coord1, coord2, l_vel=vel1, b_vel=vel2, duration=duration, executeat=executeat))
        else:
            return(f"Bad Command Coordinate System! {coords} is not a recognized coordinate system")

    def track_azel(self, az_pos, el_pos, az_vel=0.0, el_vel=0.0, duration=1, executeat=None):
        if executeat is not None:
            self.websocket.send(json.dumps({"type": "track", "id": self.message_id, "coords": "azel", "executeat": executeat, "az_pos": az_pos, "az_vel": az_vel, "el_pos": el_pos, "el_vel": el_vel, "duration": duration}))
        else:
            self.websocket.send(json.dumps({"type": "track", "id": self.message_id, "coords": "azel", "az_pos": az_pos, "az_vel": az_vel, "el_pos": el_pos, "el_vel": el_vel, "duration": duration}))
        return self._wait_for_response(self.message_id)
    
    def track_radec(self, ra_pos, dec_pos, ra_vel=0.0, dec_vel=0.0, duration=1, executeat=None):
        if executeat is not None:
            self.websocket.send(json.dumps({"type": "track", "id": self.message_id, "coords": "radec", "executeat": executeat, "ra_pos": ra_pos, "ra_vel": ra_vel, "dec_pos": dec_pos, "dec_vel": dec_vel, "duration": duration}))
        else:
            self.websocket.send(json.dumps({"type": "track", "id": self.message_id, "coords": "radec", "ra_pos": ra_pos, "ra_vel": ra_vel, "dec_pos": dec_pos, "dec_vel": dec_vel, "duration": duration}))
        return self._wait_for_response(self.message_id)

    def track_gal(self, l_pos, b_pos, l_vel=0.0, b_vel=0.0, duration=1, executeat=None):
        if executeat is not None:
            self.websocket.send(json.dumps({"type": "track", "id": self.message_id, "coords": "gal", "executeat": executeat, "l_pos": l_pos, "l_vel": l_vel, "b_pos": b_pos, "b_vel": b_vel, "duration": duration}))
        else:
            self.websocket.send(json.dumps({"type": "track", "id": self.message_id, "coords": "gal", "l_pos": l_pos, "l_vel": l_vel, "b_pos": b_pos, "b_vel": b_vel, "duration": duration}))
        return self._wait_for_response(self.message_id)

    def get_posvel(self, coords, power):
        """
        coords can be either a string "azel", "radec", "gal" or a list containing any number of those.
        """
        self.websocket.send(json.dumps({"type": "get_posvel", "id": self.message_id, "coords": coords, "power": power}))
        return self._wait_for_response(self.message_id)

if __name__ == "__main__":
    client = BigDishClient("localhost", 1234)

    #client.authenticate_connection("example", "example")
    #client.initialize_connection(kick_others=False)
    #while True:
    #    client.track_gal(162.592,4.5697, 5)
    #    time.sleep(1)
