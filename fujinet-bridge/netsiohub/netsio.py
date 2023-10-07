
import struct
import queue
from datetime import datetime
from timeit import default_timer as timer


HUB_VERSION = "v0.13"


NETSIO_DATA_BYTE        = 0x01
NETSIO_DATA_BLOCK       = 0x02
NETSIO_DATA_BYTE_SYNC   = 0x09
NETSIO_COMMAND_OFF      = 0x10
NETSIO_COMMAND_ON       = 0x11
NETSIO_COMMAND_OFF_SYNC = 0x18
NETSIO_MOTOR_OFF        = 0x20
NETSIO_MOTOR_ON         = 0x21
NETSIO_PROCEED_OFF      = 0x30
NETSIO_PROCEED_ON       = 0x31
NETSIO_INTERRUPT_OFF    = 0x40
NETSIO_INTERRUPT_ON     = 0x41
NETSIO_SPEED_CHANGE     = 0x80
NETSIO_SYNC_RESPONSE    = 0x81
NETSIO_DEVICE_DISCONNECT = 0xC0
NETSIO_DEVICE_CONNECT   = 0xC1
NETSIO_PING_REQUEST     = 0xC2
NETSIO_PING_RESPONSE    = 0xC3
NETSIO_ALIVE_REQUEST    = 0xC4
NETSIO_ALIVE_RESPONSE   = 0xC5
NETSIO_WARM_RESET       = 0xFE
NETSIO_COLD_RESET       = 0xFF

# events to manage device connection (connect, ping, alive) >= 0xC0
NETSIO_CONN_MGMT        = 0xC0

# NETSIO_SYNC_RESPONSE types
NETSIO_EMPTY_SYNC       = 0x00
NETSIO_ACK_SYNC         = 0x01

# Altirra specific
ATDEV_READY             = 0x100
ATDEV_TRANSMIT_BUFFER   = 0x101
ATDEV_DEBUG_MESSAGE     = 0x102
ATDEV_DEBUG_NOP         = 0x103
ATDEV_EMPTY_SYNC        = -1 # any value less than zero


# local TCP port for Altirra custom device communication
NETSIO_ATDEV_PORT   = 9996
# UDP port NetSIO is accepting messages from peripherals
NETSIO_PORT         = 9997

# client expiration period in seconds
#  if NetSIO HUB will not receive alive message (NETSIO_ALIVE_REQUEST) from device the device
#  connection is being considered as expired and the device is disconnected from the HUB
ALIVE_EXPIRATION = 30.0


# debug printing, disabled by default
_debug_enabled = False

def enable_debug(enable=True):
    global _debug_enabled
    _debug_enabled = enable


def debug_print(*argv, **kwargs):
    global _debug_enabled
    if _debug_enabled:
        print("{}".format(datetime.now().strftime("%H:%M:%S.%f")), *argv, **kwargs)


def info_print(*argv, **kwargs):
    print("{}".format(datetime.now().strftime("%H:%M:%S.%f")), *argv, **kwargs)


def clear_queue(q):
    try:
        while True:
            q.get_nowait()
    except queue.Empty:
        pass


class NetSIOMsg:
    def __init__(self, id, arg=None):
        self.id = id
        if arg is None:
            self.arg = bytes()
        else:
            self.arg = arg if isinstance(arg, (bytes, bytearray)) else struct.pack('B', arg)
        self.time = timer()

    def elapsed(self):
        return timer() - self.time

    def arg_str(self):
        return " ".join(["{:02X}".format(b) for b in self.arg])

    def __str__(self):
        return "{:02X}{}{}".format(
            self.id, " " if len(self.arg) else"", self.arg_str())


class NetSIOHub:
    pass

class DeviceManager():
    """Manages communication with external peripheral devices"""
    def __init__(self, port):
        self.port = port
        self.sync_tmout = 0.1 # 100 ms
        pass

    def start(self, hub:NetSIOHub):
        pass

    def stop(self):
        pass

    def to_peripheral(self, msg:NetSIOMsg):
        pass

    def connected(self):
        """Return true if any device is connected"""
        return True

class HostManager():
    """Manages communication with Atari host / Atari emulator"""
    def __init__(self):
        self.hub = None
        pass

    def run(self, hub:NetSIOHub):
        self.hub = hub
        pass

    def stop(self):
        pass