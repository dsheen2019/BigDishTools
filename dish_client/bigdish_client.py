#!/usr/bin/env python3

import time
import json
import atexit
import weakref
import threading
from websockets.sync.client import connect


# Clients that have not been closed yet, held weakly so that registering here never keeps one
# alive. At interpreter exit each is closed, which hands the server a proper websocket close
# instead of an abruptly dropped connection, without scripts having to do anything.
_open_clients = weakref.WeakSet()


@atexit.register
def _close_open_clients():
    for client in list(_open_clients):
        try:
            client.close()
        except Exception:
            pass


class BigDishClient:
    def __init__(self, server_host, server_port, response_timeout = 30.0):
        '''
        get to CONNECTED state only.

        User must then authenticate to authenticated state, and request dish control using initialize_connection

        response_timeout -- seconds to wait for a reply before raising TimeoutError. The server
        answers every request as soon as it receives it, including commands scheduled with
        executeat (those are acknowledged on receipt, not at execution time), so this only trips
        if something has actually gone wrong. Pass None to wait indefinitely.
        '''

        self.websocket = connect(f"ws://{server_host}:{server_port}")

        self.message_id = 0
        self.received_messages = {}
        self.response_timeout = response_timeout

        # Replies land on the receive thread, so every access to received_messages is guarded by
        # this condition. Waiting on it rather than polling means a reply wakes its caller as
        # soon as it arrives, instead of on the next tick of a sleep loop.
        self._response_available = threading.Condition()
        self._connection_closed = None

        # daemon so that this thread, which sits blocked on the socket until the connection ends,
        # cannot hold the interpreter open after the script itself has finished or been
        # interrupted. Without this a Ctrl-C leaves the process wedged in interpreter shutdown,
        # still answering keepalive pings, so the server goes on believing the script holds
        # control of the dish.
        self._message_recv_thread_handle = threading.Thread(target = self._message_recv_thread, daemon = True)
        self._message_recv_thread_handle.start()

        _open_clients.add(self)

    def _message_recv_thread(self):
        closed = ConnectionError("connection to the server closed")

        try:
            for message in self.websocket:
                message_decoded = json.loads(message)
                with self._response_available:
                    self.received_messages[message_decoded["id"]] = message_decoded
                    self._response_available.notify_all()
        except Exception as e:
            closed = e
        finally:
            # wake anyone still waiting so they fail straight away rather than sitting out the
            # full timeout on a connection that is never going to answer
            with self._response_available:
                self._connection_closed = closed
                self._response_available.notify_all()

    def _wait_for_response(self, id, timeout = "default"):
        if timeout == "default":
            timeout = self.response_timeout

        with self._response_available:
            satisfied = self._response_available.wait_for(
                lambda: id in self.received_messages or self._connection_closed is not None,
                timeout)

            if id in self.received_messages:
                # a reply that already arrived wins over a subsequent disconnect
                message = self.received_messages.pop(id)
            elif not satisfied:
                raise TimeoutError(f"No response to message {id} within {timeout} s.")
            else:
                raise ConnectionError(f"Connection closed while waiting for a response to message {id}.") from self._connection_closed

        self.message_id += 1
        return message

    def close(self):
        '''
        Close the connection to the server and let the receive thread finish.

        Safe to call more than once, and called automatically at interpreter exit, so scripts
        that just run to completion or get interrupted still release dish control promptly.
        '''
        _open_clients.discard(self)

        try:
            self.websocket.close()
        except Exception:
            pass

        if self._message_recv_thread_handle is not threading.current_thread():
            self._message_recv_thread_handle.join(timeout = 2.0)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False

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
