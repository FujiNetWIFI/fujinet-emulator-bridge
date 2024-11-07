#!/usr/bin/env python3

from netsiohub import deviceserver
from netsiohub.netsio import *

from enum import IntEnum
import socket, socketserver
import threading
import queue
import sys
import time
import struct
import argparse

try:
    from netsiohub.serial import *
    has_serial = True
except ModuleNotFoundError:
    has_serial = False

_start_time = timer()

def print_banner():
    print("NetSIO HUB", HUB_VERSION)


class NetSIOClient:
    def __init__(self, address, sock):
        self.address = address
        self.sock = sock
        self.expire_time = time.time() + ALIVE_EXPIRATION
        # self.cpb = 94 # default 94 CPB (19200 baud)
        self.credit = 0
        self.lock = threading.Lock()

    def expired(self, t=None):
        if t is None:
            t = time.time()
        with self.lock:
            expired = True if self.expire_time < t else False
        return expired

    def refresh(self):
        with self.lock:
            self.expire_time = time.time() + ALIVE_EXPIRATION

    def update_credit(self, credit, threshold=0):
        update = False
        with self.lock:
            if self.credit <= threshold:
                self.credit = credit
                update = True
        return update

class NetInThread(threading.Thread):
    """Thread to handle incoming network traffic"""
    def __init__(self, hub, port):
        self.hub:NetSIOHub = hub
        self.port:int = int(port)
        self.server:NetSIOServer = None
        self.server_ready = threading.Event()
        super().__init__()

    def run(self):
        debug_print("NetInThread started")
        with NetSIOServer(self.hub, self.port) as self.server:
            print("Listening for NetSIO packets on port {}".format(self.port))
            self.server_ready.set()
            self.server.serve_forever()
        self.server_ready.clear()
        debug_print("NetInThread stopped")

    def stop(self):
        debug_print("Stop NetInThread")
        if self.server is not None:
            self.server.shutdown()

class NetInBuffer:
    """Byte buffer with auto flush on size or age"""

    BUFFER_SIZE = 130 # 130 bytes
    BUFFER_MAX_AGE = 0.005 # 5 ms

    def __init__(self, server):
        self.server = server
        self.data = bytearray()
        self.lock = threading.RLock()
        self.monitor_condition = threading.Condition()
        self.monitor_event = threading.Event()
        self.tmout = 0.0
        threading.Thread(target=self.buffer_monitor).start()

    def buffer_monitor(self):
        debug_print("buffer_monitor started")
        self.monitor_condition.acquire()
        while True:
            #debug_print("buffer_monitor long waiting")
            self.monitor_condition.wait()
            tmout = self.tmout
            #debug_print("buffer_monitor tmout:", tmout)
            self.monitor_event.set()
            if tmout is None:
                break
            while True:
                #debug_print("buffer_monitor timeout waiting")
                reset = self.monitor_condition.wait(tmout)
                if not reset:
                    #debug_print("buffer_monitor expired")
                    self.monitor_event.set() # in case set_delay is waiting when we timed-out
                    self.flush()
                    break
                tmout = self.tmout
                #debug_print("buffer_monitor new tmout:", tmout)
                self.monitor_event.set()
                if tmout is None:
                    break
            if tmout is None:
                break
        self.monitor_condition.release()
        debug_print("buffer_monitor stopped")

    def set_delay(self, t):
        with self.monitor_condition:
            #debug_print("buffer_monitor notify")
            self.tmout = t
            self.monitor_event.clear()
            self.monitor_condition.notify()
            #debug_print("buffer_monitor notification sent")
        self.monitor_event.wait()
        #debug_print("buffer_monitor delay applied")

    def stop(self):
        self.set_delay(None)

    def extend(self, b:bytearray):
        with self.lock:
            self.data.extend(b)
            l = len(self.data)
        if l >= self.BUFFER_SIZE:
            self.flush()
        else:
            self.set_delay(self.BUFFER_MAX_AGE)

    def flush(self):
        msg = None
        with self.lock:
            if len(self.data):
                if len(self.data) > 1:
                    msg = NetSIOMsg(NETSIO_DATA_BLOCK, self.data)
                else:
                    msg = NetSIOMsg(NETSIO_DATA_BYTE, self.data)
                self.data = bytearray()
        if msg:
            debug_print("< NET FLUSH", msg)
            self.server.hub.handle_device_msg(msg, None)

class NetSIOServer(socketserver.UDPServer):
    """NetSIO UDP Server"""

    def __init__(self, hub:NetSIOHub, port:int):
        self.hub:NetSIOHub = hub
        self.clients_lock = threading.Lock()
        self.clients = {}
        self.last_recv = timer()
        self.sn = 0 # TODO test only
        # single bytes buffering
        self.inbuffer = NetInBuffer(self)
        super().__init__(('', port), NetSIOHandler)

    def shutdown(self):
        self.inbuffer.stop()
        super().shutdown()

    def register_client(self, address, sock):
        with self.clients_lock:
            if address not in self.clients:
                client = NetSIOClient(address, sock)
                self.clients[address] = client
                info_print("Device connected: {}  Devices: {}".format(addrtos(address), len(self.clients)))
            else:
                client = self.clients[address]
                client.sock = sock
                client.refresh()
                info_print("Device reconnected: {}  Devices: {}".format(addrtos(address), len(self.clients)))
        # give the client initial credit
        client.update_credit(DEFAULT_CREDIT) # initial credit
        self.send_to_client(client, NetSIOMsg(NETSIO_CREDIT_UPDATE, DEFAULT_CREDIT))
        # notify hub
        self.hub.handle_device_msg(NetSIOMsg(NETSIO_DEVICE_CONNECT), client)
        return client

    def deregister_client(self, address, expired=False):
        with self.clients_lock:
            try:
                client = self.clients.pop(address)
            except KeyError:
                client = None
            count = len(self.clients)
        if client is not None:
            info_print("Device disconnected{}: {}  Devices: {}".format(
                " (connection expired)" if expired else "", addrtos(address), count))
            self.hub.handle_device_msg(NetSIOMsg(NETSIO_DEVICE_DISCONNECT), client)

    def get_client(self, address):
        with self.clients_lock:
            client = self.clients.get(address)
        return client

    def send_to_client(self, client:NetSIOClient, msg):
        client.sock.sendto(struct.pack('B', msg.id) + msg.arg, client.address)
        debug_print("> NET {} {}".format(addrtos(client.address), msg))

    def send_to_all(self, msg):
        """broadcast all connected netsio devices"""
        t = time.time()
        expire = False
        with self.clients_lock:
            clients = list(self.clients.values())
        # TODO test only
        msg.arg.append(self.sn)
        self.sn = (1 + self.sn) & 255
        for c in clients:
            # skip sending to expired clients
            if c.expired(t):
                expire = True
                continue
            self.send_to_client(c, msg)
        if expire:
            # remove expired clients
            self.expire_clients()
    
    def expire_clients(self):
        t = time.time()
        with self.clients_lock:
            expired = [c for c in self.clients.values() if c.expired(t)]
        for c in expired:
            self.deregister_client(c.address, expired=True)
        
    def connected(self):
        """Return true if any client is connected"""
        with self.clients_lock:
            return len(self.clients) > 0

    def credit_clients(self):
        # send credits to waiting clients if there is a room in a queue
        credit = DEFAULT_CREDIT - self.hub.host_queue.qsize()
        if credit >= 2:
            with self.clients_lock:
                clients = list(self.clients.values())
            msg = NetSIOMsg(NETSIO_CREDIT_UPDATE, credit)
            for c in clients:
                if c.update_credit(credit):
                    self.send_to_client(c, msg)


class NetSIOHandler(socketserver.BaseRequestHandler):
    """NetSIO received packet handler"""

    def handle(self):
        data, sock = self.request
        msg = NetSIOMsg(data[0], data[1:])
        ca = self.client_address

        debug_print("< NET IN +{:.0f} {} {}".format(
            (timer()-self.server.last_recv)*1.e6,
            addrtos(ca), msg))
        self.server.last_recv = timer()

        if msg.id < NETSIO_CONN_MGMT:
            # events from connected/registered devices
            client = self.server.get_client(self.client_address)
            if client is not None:
                if client.expired():
                    # expired connection
                    self.server.deregister_client(client.address, expired=True)
                else:
                    # update expiration
                    client.refresh()
                    if msg.id == NETSIO_DATA_BYTE:
                        # buffering
                        self.server.inbuffer.extend(msg.arg)
                    else:
                        # send buffer firts, if any
                        self.server.inbuffer.flush()
                        self.server.hub.handle_device_msg(msg, client)
        else:
            # connection management
            if msg.id == NETSIO_DEVICE_DISCONNECT:
                # device disconnected, deregister client
                self.server.deregister_client(self.client_address)
            elif msg.id == NETSIO_DEVICE_CONNECT:
                # device connected, register client for netsio messages
                self.server.register_client(self.client_address, sock)
            elif msg.id == NETSIO_PING_REQUEST:
                # ping request, send ping response (always)
                self.server.send_to_client(
                    NetSIOClient(self.client_address, sock),
                    NetSIOMsg(NETSIO_PING_RESPONSE)
                )
            elif msg.id == NETSIO_ALIVE_REQUEST:
                # alive, send alive response (only if connected/registered)
                client = self.server.get_client(self.client_address)
                if client is not None:
                    client.refresh()
                    self.server.send_to_client(client, NetSIOMsg(NETSIO_ALIVE_RESPONSE))
            elif msg.id == NETSIO_CREDIT_STATUS:
                client = self.server.get_client(self.client_address)
                if client is not None and len(msg.arg):
                    # update client's credit
                    client.update_credit(msg.arg[0], 10) # threshold 10 to force credit update
                    # send new credit immediately if there is a room in a queue
                    credit = DEFAULT_CREDIT - self.server.hub.host_queue.qsize()
                    if credit >= 2 and client.update_credit(credit):
                        self.server.send_to_client(client, NetSIOMsg(NETSIO_CREDIT_UPDATE, credit))


class NetOutThread(threading.Thread):
    """Thread to send "messages" to connected netsio devices"""
    def __init__(self, q:queue.Queue, server:NetSIOServer):
        self.queue:queue.Queue = q
        self.server:NetSIOServer = server
        super().__init__()

    def run(self):
        debug_print("NetOutThread started")
        while True:
            msg = self.queue.get()
            if msg is None:
                break
            self.server.send_to_all(msg)

        debug_print("NetOutThread stopped")

    def stop(self):
        debug_print("Stop NetOutThread")
        clear_queue(self.queue)
        self.queue.put(None) # stop sign
        self.join()


class NetSIOManager(DeviceManager):
    """Manages NetSIO (SIO over UDP) traffic"""

    def __init__(self, port=NETSIO_PORT):
        super().__init__(port)
        self.device_queue = queue.Queue(16)
        self.netin_thread:NetInThread = None
        self.netout_thread:NetOutThread = None

    def start(self, hub):
        print("UDP port (NetSIO):", self.port)

        # network receiver
        self.netin_thread = NetInThread(hub, self.port)
        self.netin_thread.start()

        # wait for server to be created
        if not self.netin_thread.server_ready.wait(3):
            print("Time out waiting for NetSIOServer to start")

        # network sender
        self.netout_thread = NetOutThread(self.device_queue, self.netin_thread.server)
        self.netout_thread.start()

    def stop(self):
        debug_print("Stop NetSIOManager")
        if self.netin_thread:
            self.netin_thread.stop()
            self.netin_thread = None
        if self.netout_thread:
            self.netout_thread.stop()
            self.netout_thread = None

    def to_peripheral(self, msg):
        if msg.id in (NETSIO_COLD_RESET, NETSIO_WARM_RESET):
            debug_print("CLEAR DEV QUEUE")
            clear_queue(self.device_queue)

        if self.device_queue.full():
            debug_print("device queue FULL")
        else:
            debug_print("device queue [{}]".format(self.device_queue.qsize()))

        self.device_queue.put(msg)
        # debug_print("> DEV", msg)

    def connected(self):
        """Return true if any device is connected"""
        return self.netin_thread.server.connected()

    def credit_clients(self):
        return self.netin_thread.server.credit_clients()

class AtDevManager(HostManager):
    """Altirra custom device manager"""
    def __init__(self, arg_parser):
        super().__init__()
        self.arg_parser = arg_parser
        self.hub = None

    def run(self, hub):
        self.hub = hub
        deviceserver.run_deviceserver(AtDevHandler, NETSIO_ATDEV_PORT, self.arg_parser, self.run_server)

    def run_server(self, server):
        # make hub available to handler (via server object)
        server.hub = self.hub
        server.serve_forever()

    def stop(self):
        # TODO stop AtDevThread, if still running
        pass


class AtDevHandler(deviceserver.DeviceTCPHandler):
    """Handler to communicate with netsio.atdevice which lives in Altirra"""
    def __init__(self, *args, **kwargs):
        debug_print("AtDevHandler")
        self.hub = None
        self.atdev_ready = None
        self.atdev_thread = None
        self.busy_at = timer()
        self.idle_at = timer()
        self.emu_ts = 0
        super().__init__(*args, **kwargs)

    def handle(self):
        """handle messages from netsio.atdevice"""
        # start thread for outgoing messages to atdevice
        self.hub = self.server.hub
        self.atdev_ready = threading.Event()
        self.atdev_ready.set()
        host_queue = self.hub.host_connected(self)
        self.atdev_thread = AtDevThread(host_queue, self)
        self.atdev_thread.start()

        try:
            super().handle()
        except ConnectionResetError:
            info_print("Host reset connection")
        finally:
            self.hub.host_disconnected()
            self.atdev_thread.stop()

    def handle_script_post(self, event: int, arg: int, timestamp: int):
        """handle post_message from netsio.atdevice"""
        ts = timer()
        self.emu_ts = timestamp
        msg:NetSIOMsg = None

        if event == ATDEV_READY:
            # POKEY is ready to receive serial data
            msg = NetSIOMsg(event)
        elif event == NETSIO_DATA_BYTE:
            # serial byte from POKEY
            msg = NetSIOMsg(event, arg)
            # self.hub.handle_host_msg(NetSIOMsg(event, arg))
        elif event == NETSIO_SPEED_CHANGE:
            # serial output speed changed
            msg = NetSIOMsg(event, struct.pack("<L", arg))
            # self.hub.handle_host_msg(NetSIOMsg(event, struct.pack("<L", arg)))
        elif event < 0x100: # fit byte
            # all other (one byte) events from atdevice
            msg = NetSIOMsg(event)
            if event == NETSIO_COLD_RESET:
                self.atdev_ready.set()
            # send to connected devices
            msg = NetSIOMsg(event)
            # self.hub.handle_host_msg(NetSIOMsg(event))
        elif event == ATDEV_DEBUG_NOP:
            msg = NetSIOMsg(event)

        if msg is None:
            debug_print("> ATD {:02X} {:02X} ++{} -> {}".format(event, arg, timestamp-self.emu_ts))
            info_print("Invalid ATD")
            return

        msg.time = ts
        debug_print("> ATD {:02X} {:02X} ++{} -> {}".format(event, arg, timestamp-self.emu_ts, msg))
        if event == ATDEV_READY:
            self.set_rtr()
        else:
            # send message to connected device
            self.hub.handle_host_msg(msg)

    def handle_script_event(self, event: int, arg: int, timestamp: int) -> int:
        ts = timer()
        self.emu_ts = timestamp
        msg:NetSIOMsg = None
        local = False

        result = ATDEV_EMPTY_SYNC
        if event == NETSIO_DATA_BYTE_SYNC:
            msg = NetSIOMsg(event, arg) # request sn will be appended
        elif event == NETSIO_COMMAND_OFF_SYNC:
            msg = NetSIOMsg(event) # request sn will be appended
        elif event == NETSIO_DATA_BLOCK:
            msg = NetSIOMsg(event) # data block will be read
        elif event == ATDEV_DEBUG_NOP:
            msg = NetSIOMsg(event, arg)
            local = True
            result = arg

        if msg is None:
            debug_print("> ATD CALL {:02X} {:02X} ++{}".format(event, arg, timestamp-self.emu_ts))
            info_print("Invalid ATD CALL")
            debug_print("< ATD RESPONSE {}".format(result))
            return result

        msg.time = ts
        debug_print("> ATD CALL {:02X} {:02X} ++{} -> {}".format(event, arg, timestamp-self.emu_ts, msg))
        if event == NETSIO_DATA_BLOCK:
            # get data from rxbuffer segment
            debug_print("< ATD READ_BUFFER", arg)
            msg.arg = self.req_read_seg_mem(1, 0, arg)
            debug_print("  ATD ->", msg)
        if not local:
            result = self.hub.handle_host_msg_sync(msg)
        debug_print("< ATD RESPONSE {} = 0x{:02X} +{:.0f}".format(result, result, msg.elapsed_us()))
        return result

    def handle_coldreset(self, timestamp):
        debug_print("> ATD COLD RESET")
        self.emu_ts = timestamp
        # In some cases Altirra does send Cold reset message without cold-resetting emulated Atari
        # self.hub.handle_host_msg(NetSIOMsg(NETSIO_COLD_RESET))

    def handle_warmreset(self, timestamp):
        debug_print("> ATD WARM RESET")
        self.emu_ts = timestamp
        self.hub.handle_host_msg(NetSIOMsg(NETSIO_WARM_RESET))

    def clear_rtr(self):
        """Clear Ready To Receive"""
        self.busy_at = timer()
        self.atdev_ready.clear()
        debug_print("ATD BUSY  idle time: {:.0f}".format((self.busy_at-self.idle_at)*1.e6))

    def set_rtr(self):
        """Set Ready To receive"""
        self.idle_at = timer()
        self.atdev_ready.set()
        debug_print("ATD READY busy time: {:.0f}".format((self.idle_at-self.busy_at)*1.e6))

    def wait_rtr(self, timeout):
        """Wait for ready receiver"""
        return self.atdev_ready.wait(timeout)

class AtDevThread(threading.Thread):
    """Thread to send "messages" to Altrira atdevice"""
    def __init__(self, queue, handler):
        self.queue = queue
        self.atdev_handler = handler
        self.busy_at = timer()
        self.stop_flag = threading.Event()
        super().__init__()

    def run(self):
        debug_print("AtDevThread started")

        # # TODO debug text message
        # # place message to netsio.atdevice textbuffer i.e. segment 2
        # msg = NetSIOMsg(ATDEV_DEBUG_MESSAGE, b"Hi")
        # self.atdev_handler.req_write_seg_mem(2, 0, msg.arg)
        # msglen = len(msg.arg)
        # debug_print("< ATD +{:.0f} MSG [{}] {}".format(msg.elapsed_us(), msglen, msg.arg_str()))
        # # instruct netsio.atdevice to send rxbuffer to emulated Atari
        # self.atdev_handler.req_interrupt(ATDEV_DEBUG_MESSAGE, msglen)
        # debug_print("< ATD +{:.0f} {:02X} {:02X}".format(msg.elapsed_us(), ATDEV_DEBUG_MESSAGE, msglen))

        while True:
            msg = self.queue.get()
            if self.stop_flag.is_set():
                break

            if not self.atdev_handler.wait_rtr(5): # TODO adjustable
                info_print("ATD TIMEOUT")
                # TODO timeout recovery
                clear_queue(self.queue)
                self.atdev_handler.set_rtr()

            if self.stop_flag.is_set():
                break

            if self.queue.qsize() < 2:
                self.atdev_handler.hub.credit_clients()

            if msg.id in (NETSIO_DATA_BYTE, NETSIO_DATA_BLOCK, NETSIO_BUS_IDLE):
                # send byte and send buffer makes POKEY busy and
                # we have to receive confirmation when it is ready again
                # prior sending more data
                self.atdev_handler.clear_rtr()

            if msg.id == NETSIO_DATA_BLOCK:
                rxsize = len(msg.arg)
                if rxsize <= 6:
                    # prepare compact short data block
                    aux1 = ATDEV_TRANSMIT_BUFFER | (rxsize << 9)
                    aux2 = 0
                    # place firts 2 bytes into aux1
                    if rxsize:
                        aux1 |= (msg.arg[0] << 16)
                    if rxsize > 1:
                        aux1 |= (msg.arg[1] << 24)
                    # place next 4 bytes into aux2
                    if rxsize > 2:
                        aux2 = msg.arg[2]
                    if rxsize > 3:
                        aux2 |= (msg.arg[3] << 8)
                    if rxsize > 4:
                        aux2 |= (msg.arg[4] << 16)
                    if rxsize > 5:
                        aux2 |= (msg.arg[5] << 24)
                    debug_print("< ATD {:08X}:WRITE_&_TRANSMIT_BUFFER 0x{:08X} +{:.0f} <- {}".format(
                        aux1, aux2, msg.elapsed_us(), msg))
                    self.atdev_handler.req_interrupt(aux1, aux2)
                else:
                    # place serial data to netsio.atdevice rxbuffer i.e. segment 0
                    debug_print("< ATD WRITE_BUFFER {} <- {}".format(rxsize, msg))
                    self.atdev_handler.req_write_seg_mem(0, 0, msg.arg)
                    # instruct netsio.atdevice to send rxbuffer to emulated Atari
                    debug_print("< ATD {:02X}:TRANSMIT_BUFFER {} +{:.0f}".format(
                        ATDEV_TRANSMIT_BUFFER, rxsize, msg.elapsed_us()))
                    self.atdev_handler.req_interrupt(ATDEV_TRANSMIT_BUFFER, rxsize)
            elif msg.id == NETSIO_DATA_BYTE:
                # serial byte from remote device
                debug_print("< ATD {}".format(msg))
                self.atdev_handler.req_interrupt(msg.id, msg.arg[0])
            elif msg.id == NETSIO_SPEED_CHANGE:
                # speed change
                if len(msg.arg) == 4:
                    debug_print("< ATD {}".format(msg))
                    self.atdev_handler.req_interrupt(msg.id, struct.unpack('<L', msg.arg)[0])
                else:
                    info_print("Invalid NETSIO_SPEED_CHANGE message")
            elif msg.id == NETSIO_BUS_IDLE:
                # speed change
                if len(msg.arg) == 2:
                    debug_print("< ATD {}".format(msg))
                    self.atdev_handler.req_interrupt(msg.id, struct.unpack('<H', msg.arg)[0])
                else:
                    info_print("Invalid NETSIO_BUS_IDLE message")
            else:
                # all other
                debug_print("< ATD {}".format(msg))
                self.atdev_handler.req_interrupt(msg.id, msg.arg[0] if len(msg.arg) else 0)

        debug_print("AtDevThread stopped")

    def stop(self):
        debug_print("Stop AtDevThread")
        self.stop_flag.set()
        # clear_queue(self.queue) # things can cumulate here ...
        self.queue.put(None) # unblock queue.get()
        self.join()


class NetSIOHub:
    """HUB connecting NetSIO devices with Atari host"""

    class SyncRequest:
        """Synchronized request-response"""
        def __init__(self):
            self.sn = 0
            self.request = None
            self.response = None
            self.lock = threading.Lock()
            self.completed = threading.Event()

        def set_request(self, request):
            with self.lock:
                self.sn = (self.sn + 1) & 255
                self.request = request
                self.completed.clear()
            return self.sn

        def set_response(self, response, sn):
            with self.lock:
                if self.request is not None and self.sn == sn:
                    self.request = None
                    self.response = response
                    self.completed.set()

        def get_response(self, timeout=None, timout_value=None):
            if self.completed.wait(timeout):
                with self.lock:
                    self.request = None
                    return self.response
            else:
                with self.lock:
                    self.request = None
                    return timout_value

        def check_request(self):
            with self.lock:
                return self.request, self.sn

    def __init__(self, device_manager:DeviceManager, host_manager:HostManager):
        self.device_manager = device_manager
        self.host_manager = host_manager
        self.host_queue = queue.Queue(8) # max 3-4 items should be there, anyhow make it bit larger, to avoid blocked netin thread
        self.host_ready = threading.Event()
        self.host_handler:AtDevHandler = None
        self.sync = NetSIOHub.SyncRequest()

    def run(self):
        try:
            self.device_manager.start(self)
            self.host_manager.run(self)
        finally:
            self.device_manager.stop()
            self.host_manager.stop()

    def host_connected(self, host_handler:AtDevHandler): # TODO replace call to AtDevHandler.clear_rtr()
        info_print("Host connected")
        self.host_handler = host_handler
        self.host_ready.set()
        return self.host_queue

    def host_disconnected(self):
        info_print("Host disconnected")
        self.host_ready.clear()
        self.host_handler = None
        clear_queue(self.host_queue)

    def handle_host_msg(self, msg:NetSIOMsg):
        """handle message from Atari host emulator, emulation is running"""
        if msg.id in (NETSIO_COLD_RESET, NETSIO_WARM_RESET):
            info_print("HOST {} RESET".format("COLD" if msg.id == NETSIO_COLD_RESET else "WARM"))
            # # clear I/O queues on emulator cold / warm reset
            # debug_print("CLEAR HOST QUEUE")
            # clear_queue(self.host_queue)
        # send message down to connected peripherals
        self.device_manager.to_peripheral(msg)

    def handle_host_msg_sync(self, msg:NetSIOMsg) ->int:
        """handle message from Atari host emulator, emulation is paused, emulator is waiting for reply"""
        if msg.id == NETSIO_DATA_BLOCK:
            self.handle_host_msg(msg) # send to devices
            return ATDEV_EMPTY_SYNC # return no ACK byte
        # handle sync request
        msg.arg.append(self.sync.set_request(msg.id)) # append request sn prior sending
        clear_queue(self.host_queue)
        if not self.device_manager.connected():
            # shortcut: no device is connected, set response now
            self.sync.set_response(ATDEV_EMPTY_SYNC, self.sync.sn) # no ACK byte
        else:
            self.handle_host_msg(msg) # send to devices
        result = self.sync.get_response(self.device_manager.sync_tmout, ATDEV_EMPTY_SYNC)
        return result

    def handle_device_msg(self, msg:NetSIOMsg, device:NetSIOClient):
        """handle message from peripheral device"""
        if not self.host_ready.is_set():
            # discard, host is not connected
            return

        # handle sync request/response
        req, sn = self.sync.check_request()
        if req is not None:
            if msg.id == NETSIO_SYNC_RESPONSE and msg.arg[0] == sn:
                # we received response to current SYNC request
                if msg.arg[1] == NETSIO_EMPTY_SYNC:
                    # empty response, no ACK/NAK
                    self.sync.set_response(ATDEV_EMPTY_SYNC, sn) # no ACK byte
                else:
                    # response with ACK/NAK byte and sync write size
                    self.host_handler.clear_rtr()
                    self.sync.set_response(NETSIO_SYNC_RESPONSE |
                                           msg.arg[2] << 8 | (msg.arg[3] << 16) | (msg.arg[4] << 24), sn)
                return
            elif msg.id in (NETSIO_DATA_BYTE, NETSIO_DATA_BLOCK):
                debug_print("discarding", msg)
                return
            else:
                debug_print("passed", msg)

        if msg.id == NETSIO_SYNC_RESPONSE and msg.arg[1] != NETSIO_EMPTY_SYNC:
            # TODO 
            # host is not interested into this sync response
            # but there is a byte inside response, deliver it as normal byte to host ...
            debug_print("replace", msg)
            msg.id = NETSIO_DATA_BYTE
            msg.arg = bytes( (msg.arg[2],) )

        if self.host_queue.full():
            debug_print("host queue FULL")
        else:
            debug_print("host queue [{}]".format(self.host_queue.qsize()))

        self.host_queue.put(msg)

    def credit_clients(self):
        self.device_manager.credit_clients()

# workaround for calling parse_args() twice
def get_arg_parser(full=True):
    arg_parser = argparse.ArgumentParser(description = 
            "Connects NetSIO protocol (SIO over UDP) talking peripherals with "
            "NetSIO Altirra custom device (localhost TCP).")
    port_grp = arg_parser.add_mutually_exclusive_group()
    port_grp.add_argument('--netsio-port', type=int, default=NETSIO_PORT,
        help='Change UDP port used by NetSIO peripherals (default {})'.format(NETSIO_PORT))
    #serial_grp = port_grp.add_argument_group("Serial port")
    port_grp.add_argument('--serial',
        help='Switch to serial port mode. Specify serial port (device) to use for communication with peripherals.')
    arg_parser.add_argument('--command', default='RTS', choices=['RTS','DTR'],
        help='Specify how is COMMAND signal connected, value can be RTS (default) or DTR')
    arg_parser.add_argument('--proceed', default='CTS', choices=['CTS','DSR'],
        help='Specify how is PROCEED signal connected, value can be CTS (default) or DSR')
    arg_parser.add_argument('-d', '--debug', dest='debug', action='store_true', help='Print debug output')
    if full:
        arg_parser.add_argument('--port', type=int, default=NETSIO_ATDEV_PORT,
            help='Change TCP port used by Altirra NetSIO custom device (default {})'.format(NETSIO_ATDEV_PORT))
        arg_parser.add_argument('-v', '--verbose', dest='verbose', action='store_true',
            help='Log emulation device commands')
    return arg_parser


def main():
    print("__file__:", __file__)
    print("sys.executable:", sys.executable)
    print("sys.version:", sys.version)
    print("sys.path:")
    print("\n".join(sys.path))
    print("sys.argv", sys.argv)

    print_banner()

    socketserver.TCPServer.allow_reuse_address = True
    args = get_arg_parser().parse_args()

    if args.debug:
        enable_debug()

    # get device manager (to talk to peripheral device)
    if args.serial:
        if has_serial:
            device_manager = SerialSIOManager(args.serial, args.command, args.proceed)
        else:
            print("pySerial module was not found. To install pySerial module run 'python -m pip install pyserial'.")
            return -1
    else:
        device_manager = NetSIOManager(args.netsio_port)

    # get host manager (to talk to Atari host emulator)
    host_manager = AtDevManager(get_arg_parser(False))

    # hub for host <-> devices communication
    hub = NetSIOHub(device_manager, host_manager)

    try:
        hub.run()
    except KeyboardInterrupt:
        print("\nStopped from keyboard")

    return 0
