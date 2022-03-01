# Device server for Altirra custom devices
# Copyright (C) 2020 Avery Lee, All rights reserved.
#
# This software is provided 'as-is', without any express or implied
# warranty.  In no event will the authors be held liable for any
# damages arising from the use of this software.
# 
# Permission is granted to anyone to use this software for any purpose,
# including commercial applications, and to alter it and redistribute it
# freely, subject to the following restrictions:
# 
# 1. The origin of this software must not be misrepresented; you must
#    not claim that you wrote the original software. If you use this
#    software in a product, an acknowledgment in the product
#    documentation would be appreciated but is not required.
# 2. Altered source versions must be plainly marked as such, and must
#    not be misrepresented as being the original software.
# 3. This notice may not be removed or altered from any source
#    distribution.


import socketserver
import struct
import signal
import sys
import argparse

class DeviceTCPHandler(socketserver.BaseRequestHandler):
    """
    Base socketserver handler for implementing the custom device server
    protocol. You should subclass this type in your own code and implement
    handle_*() methods. Use req_*() methods to call back into the emulator.
    """

    def __init__(self, *args, **kwargs):
        self.verbose = False
        self.handlers = {};

        self.handlers[0] = ("None", self.handle_none)
        self.handlers[1] = ("Debug read byte", self.wrap_debugreadbyte)
        self.handlers[2] = ("Read byte", self.wrap_readbyte)
        self.handlers[3] = ("Write byte", self.wrap_writebyte)
        self.handlers[4] = ("Cold reset", self.wrap_coldreset)
        self.handlers[5] = ("Warm reset", self.wrap_warmreset)
        self.handlers[6] = ("Error", self.handle_error)
        self.handlers[7] = ("Script event", self.wrap_script_event)
        self.handlers[8] = ("Script post", self.handle_script_post)

        self.counter = 0

        super().__init__(*args, **kwargs)

    def handle(self):
        self.verbose = self.server.cmdline_args.verbose

        print("Connection received from emulator")

        while True:
            command_packet = bytearray()

            while len(command_packet) < 17:
                command_subpacket = self.request.recv(17 - len(command_packet))
                if len(command_subpacket) == 0:
                    print("Connection closed")
                    return

                command_packet.extend(command_subpacket)

            command_id, param1, param2, timestamp = struct.unpack('<BIiQ', command_packet)

            try:
                command_name, handler = self.handlers[command_id]
            except KeyError:
                print("Unhandled command {:02X} - closing connection.".format(command_id))
                # self.request.close()
                if self.verbose:
                    print("{1:016X} {0:02X}({2:08X}, {3:08X})".format(command_id, timestamp, param1, param2))
                return

            if self.verbose:
                print("{1:016X} {0}({2:08X}, {3:08X})".format(command_name, timestamp, param1, param2))

            handler(param1, param2, timestamp)

    def wrap_debugreadbyte(self, address, param2, timestamp) -> int:
        rvalue = self.handle_debugreadbyte(address, timestamp)

        self.request.sendall(struct.pack('<Bi', 1, rvalue))

    def wrap_readbyte(self, address, param2, timestamp) -> int:
        rvalue = self.handle_readbyte(address, timestamp)

        self.request.sendall(struct.pack('<Bi', 1, rvalue))

    def wrap_writebyte(self, param1, param2, timestamp) -> int:
        self.handle_writebyte(param1, param2, timestamp)
        self.request.sendall(b'\x01\0\0\0\0')

    def wrap_coldreset(self, param1, param2, timestamp) -> int:
        self.handle_coldreset(timestamp)
        self.request.sendall(b'\x01\0\0\0\0')

    def wrap_warmreset(self, param1, param2, timestamp) -> int:
        self.handle_warmreset(timestamp)
        self.request.sendall(b'\x01\0\0\0\0')

    def wrap_script_event(self, param1, param2, timestamp) -> int:
        self.request.sendall(struct.pack('<Bi', 1, self.handle_script_event(param1, param2, timestamp)))

    def handle_none(self, param1, param2, timestamp) -> int:
        pass

    def handle_debugreadbyte(self, address, timestamp) -> int:
        return self.counter

    def handle_readbyte(self, address, timestamp) -> int:
        v = self.counter
        self.counter = (self.counter + 1) & 0xFF
        return v

    def handle_writebyte(self, address, value, timestamp):
        self.counter = value

    def handle_coldreset(self, timestamp):
        pass

    def handle_warmreset(self, timestamp):
        pass

    def handle_error(self, param1, param2, timestamp) -> int:
        msg = self._readall(param2).decode('utf-8')
        print("Error from emulator: " + msg)
        return 0

    def handle_script_event(self, param1, param2, timestamp) -> int:
        return 0

    def handle_script_post(self, param1, param2, timestamp):
        pass

    def req_enable_layer(self, layer_index: int, read: bool, write: bool):
        self.request.sendall(struct.pack('<BBB', 2, layer_index, (2 if read else 0) + (1 if write else 0)))

    def req_set_layer_offset(self, layer_index: int, offset: int):
        self.request.sendall(struct.pack('<BBI', 3, layer_index, offset))

    def req_set_layer_segment_and_offset(self, layer_index: int, segment_index: int, segment_offset: int):
        self.request.sendall(struct.pack('<BBBI', 4, layer_index, segment_index, segment_offset))

    def req_set_layer_readonly(self, layer_index: int, ro: bool):
        self.request.sendall(struct.pack('<BBB', 5, layer_index, 1 if ro else 0))

    def req_read_seg_mem(self, segment_index: int, offset: int, len: int):
        if offset < 0:
            raise ValueError('Invalid segment offset')

        if len <= 0:
            raise ValueError('Invalid length')

        self.request.sendall(struct.pack('<BBII', 6, segment_index, offset, len))
        return self._readall(len)

    def req_write_seg_mem(self, segment_index: int, offset: int, data:bytes):
        if offset < 0:
            raise ValueError('Invalid segment offset')

        self.request.sendall(struct.pack('<BBII', 7, segment_index, offset, len(data)))
        self.request.sendall(data)

    def req_copy_seg_mem(self, dst_segment_index: int, dst_offset: int, src_segment_index: int, src_offset: int, len: int):
        if dst_offset < 0:
            raise ValueError('Invalid destination segment offset')

        if src_offset < 0:
            raise ValueError('Invalid source segment offset')

        if len <= 0:
            raise ValueError('Invalid copy length')

        self.request.sendall(struct.pack('<BBIBII', 8, dst_segment_index, dst_offset, src_segment_index, src_offset, len))

    def req_interrupt(self, aux1: int, aux2: int):
        self.request.sendall(struct.pack('<BII', 9, aux1, aux2))

    def _readall(self, readlen):
        seg_data = bytearray()
        while len(seg_data) < readlen:
            seg_subdata = self.request.recv(readlen - len(seg_data))
            if len(seg_subdata) == 0:
                raise ConnectionError

            seg_data.extend(seg_subdata)

        return seg_data

def print_banner():
    print("Altirra Custom Device Server v0.7")
    print()

def run_deviceserver(
    handler: type,
    port: int = 6502,
    arg_parser = argparse.ArgumentParser(description = "Starts a localhost TCP server to handle emulator requests for a custom device."),
    run_handler = None
):
    """
    Bootstrap the device server. Call this from your startup module to print
    the startup banner, parse command line arguments, and run the TCP server.
    """

    print_banner()

    verbose = False
    force_sdhc = False

    arg_parser.add_argument('--port', type=int, default=port, help='Change TCP port (default: {})'.format(port))
    arg_parser.add_argument('-v', '--verbose', dest='verbose', action='store_true', help='Log emulation device commands')

    args = arg_parser.parse_args()

    with socketserver.TCPServer(("localhost", args.port), handler) as server:
        server.cmdline_args = args

        print("Waiting for localhost connection from emulator on port {} -- Ctrl+Break to stop".format(args.port))

        if run_handler is not None:
            run_handler(server)
        else:
            server.serve_forever()

if __name__ == '__main__':
    print_banner()
    print("""deviceserver.py is not meant to be run directly. It is a framework for
building your own device server to be used with a custom device specified in an
.atdevice file.""")
