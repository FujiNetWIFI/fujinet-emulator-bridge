

from netsiohub.netsio import *
import serial
import threading
import time


class SerialSIOManager:
    pass

class SerInThread(threading.Thread):
    """Thread to handle incoming serial data"""
    def __init__(self, manager:SerialSIOManager, hub:NetSIOHub):
        self.manager:SerialSIOManager = manager
        self.hub:NetSIOHub = hub
        self.serial:serial.Serial = manager.serial
        self.stop_flag = threading.Event()
        self.get_proceed = manager.get_proceed
        super().__init__()

    def run(self):

        def buffer_age():
            return timer() - buffer_timestamp
        
        def buffer_append(_b:bytes):
            ts = timer() #if len(buffer) == 0 else buffer_timestamp
            buffer.extend(_b)
            return ts

        BUFFER_SIZE = 130 #65 bytes
        BUFFER_MAX_AGE = 0.015 # 15 ms

        proceed_save = self.get_proceed()

        debug_print("SerInThread started")
        buffer = bytearray()
        buffer_timestamp = 0.0
        msg = None
        errors = 0

        # read data + TODO poll proceed
        while not self.stop_flag.is_set():
            # anything SerOutThread needs to do?
            if not self.manager.allow_read.is_set():
                self.yield_serial_output()
                continue # repeat (handle output with priority)

            # handle proceed signal
            try:
                proceed = self.get_proceed()
            except Exception as e:
                # ignore serial port exceptions
                print("Serial port error:", e)
                errors += 1
            else:
                if proceed != proceed_save:
                    proceed_save = proceed
                    self.hub.handle_device_msg(
                        NetSIOMsg(NETSIO_PROCEED_ON if proceed else NETSIO_PROCEED_OFF),
                        None)
                    debug_print("< SER PROCEED", "ON" if proceed else "OFF")

            # read (with timeout) bytes from serial port
            try:
                d = self.serial.read(BUFFER_SIZE-len(buffer))
            except Exception as e:
                # ignore serial port exceptions
                print("Serial port error:", e)
                d = bytes()
                errors += 1

            if errors >= 10:
                print("Suspending SerInThread")
                time.sleep(5)
                print("SerInThread resumed")
                errors = 0

            if len(d):
                # data was read
                debug_print("< SER IN [{}] {}".format(len(d), " ".join(["{:02X}".format(b) for b in d])))
                if self.manager.sync_flag.is_set():
                    # send sync response if sync flag is set
                    msg = NetSIOMsg(NETSIO_SYNC_RESPONSE, bytes((self.manager.sync_num, 1, d[0], 0, 0)))
                    self.manager.sync_flag.clear()
                    debug_print("= SER SYNC OFF")
                    # keep the rest in buffer
                    buffer_timestamp = buffer_append(d[1:])
                else:
                    # place data into buffer
                    buffer_timestamp = buffer_append(d)
                    # send buffer when full
                    if len(buffer) >= BUFFER_SIZE:
                        msg = NetSIOMsg(NETSIO_DATA_BLOCK, buffer)
                        buffer = bytearray() # reset buffer
            else:
                # read timeout, no new data
                # if buffer aged send whatever is in buffer
                if len(buffer) and buffer_age() > BUFFER_MAX_AGE:
                    debug_print("buffer age: {:.0f}".format(buffer_age() * 1e6))
                    if len(buffer) == 1:
                        msg = NetSIOMsg(NETSIO_DATA_BYTE, buffer)
                    else:
                        msg = NetSIOMsg(NETSIO_DATA_BLOCK, buffer)
                    buffer = bytearray() # reset buffer
            # anything to send?
            if msg:
                self.hub.handle_device_msg(msg, None)
                debug_print("< SER [{}] {}".format(1+len(msg.arg), msg))
                msg = None
        debug_print("SerInThread stopped")

    def stop(self):
        debug_print("Stop SerInThread")
        self.stop_flag.set()
        self.join()

    def yield_serial_output(self):
        #debug_print("SerIn:  3 - pausing")
        with self.manager.read_paused:
            #debug_print("SerIn:  4 - notify SerOut")
            self.manager.read_paused.notify()
            #debug_print("SerIn:  5 - notification sent")
        #debug_print("SerIn:  6 - paused")
        debug_print("SerIn paused")
        self.manager.allow_read.wait()
        #debug_print("SerIn:  9 - resumed")
        debug_print("SerIn resumed")


class SerOutThread(threading.Thread):
    """Thread to send "messages" to connected netsio devices"""
    def __init__(self, manager:SerialSIOManager, hub:NetSIOHub, q:queue.Queue):
        self.manager:SerialSIOManager = manager
        self.hub:NetSIOHub = hub
        self.queue:queue.Queue = q
        self.serial:serial.Serial = manager.serial
        self.assert_command = manager.assert_command
        super().__init__()

    def run(self):
        debug_print("SerOutThread started")
        self.assert_command(False)
        self.manager.read_paused.acquire()
        while True:
            msg = self.queue.get()
            if msg is None:
                break
            self.update_serial_port(msg)
        self.manager.read_paused.release()
        debug_print("SerOutThread stopped")

    def stop(self):
        debug_print("Stop SerOutThread")
        clear_queue(self.queue)
        self.queue.put(None) # stop sign
        self.join()

    def pause_serial_input(self):
        #debug_print("SerOut: 1 - pause SerIn")
        self.manager.allow_read.clear()
        #debug_print("SerOut: 2 - wait for SerIn")
        self.manager.read_paused.wait()
        #debug_print("SerOut: 7 - notification received")

    def resume_serial_input(self):
        #debug_print("SerOut: 8 - resume SerIn")
        self.manager.allow_read.set()

    def update_serial_port(self, msg:NetSIOMsg):
        if msg.id in (NETSIO_COMMAND_OFF, NETSIO_COMMAND_OFF_SYNC):
            self.assert_command(False)
            if msg.id == NETSIO_COMMAND_OFF_SYNC:
                self.manager.sync_flag.clear()
                self.manager.sync_num = msg.arg[0]
                self.manager.sync_flag.set()
                debug_print("= SER SYNC ON")
            debug_print("> SER COMMAND OFF")
        elif msg.id in (NETSIO_DATA_BYTE, NETSIO_DATA_BYTE_SYNC, NETSIO_DATA_BLOCK):
            self.serial.write(msg.arg)
            if msg.id == NETSIO_DATA_BYTE_SYNC:
                self.manager.sync_flag.clear()
                self.manager.sync_num = msg.arg[1]
                self.manager.sync_flag.set()
                debug_print("= SER SYNC ON")
            debug_print("> SER OUT +{:.0f} [{}] {}".format(
                        msg.elapsed() * 1.e6,
                        len(msg.arg), 
                        msg.arg_str()))
        elif msg.id == NETSIO_COMMAND_ON:
            #self.pause_serial_input()
            #self.serial.reset_input_buffer()
            #self.serial.reset_output_buffer()
            self.assert_command(True)
            debug_print("> SER COMMAND ON")
            #self.resume_serial_input()
        elif msg.id == NETSIO_SPEED_CHANGE:
            # host changed port speed
            baud = struct.unpack('<L', msg.arg)[0]
            self.pause_serial_input()
            self.serial.reset_input_buffer()
            self.serial.reset_output_buffer()
            self.serial.baudrate = int(baud*0.979)
            debug_print("= SER SPEED {} ({})".format(baud, int(baud*0.97)))
            # notify host that device changed speed too (let's hope)
            self.hub.handle_device_msg(msg, None)
            self.resume_serial_input()
        elif msg.id in (NETSIO_WARM_RESET, NETSIO_COLD_RESET):
            self.pause_serial_input()
            self.serial.reset_input_buffer()
            self.serial.reset_output_buffer()
            self.serial.baudrate = 19200
            self.manager.sync_flag.clear()
            debug_print("= SER RESET")
            self.resume_serial_input()


class SerialSIOManager(DeviceManager):
    """Manages SIO traffic over serial port"""

    def __init__(self, port, command_on, proceed_on):
        super().__init__(port)
        self.sync_tmout = 0.080 # TODO try 25 ms
        self.device_queue = queue.Queue(16)
        self.sync_flag = threading.Event()
        self.sync_num:int = 0
        self.in_thread:threading.Thread = None
        self.out_thread:threading.Thread = None
        self.serial:serial.Serial = None
        self.lock = threading.Lock()
        self.allow_read = threading.Event()
        self.read_paused = threading.Condition()
        self.command_on = command_on.upper()
        self.proceed_on = proceed_on.upper()
        self.assert_command = self.set_none
        self.get_proceed = self.get_false

    def start(self, hub):
        # open serial port and start threads
        print("Serial port:", self.port)
        try:
            self.serial = serial.Serial(self.port, 19200, timeout=0.002)
        except:
            self.serial = None
            print("Failed to open serial port")
        if self.serial:
            # command line (output)
            if self.command_on == 'RTS':
                self.assert_command = self.set_rts
                print("RTS -> COMMAND")
            elif self.command_on == 'DTR':
                self.assert_command = self.set_dtr
                print("DTR -> COMMAND")
            else:
                print("COMMAND not configured!")
            # proceed line (input)
            if self.proceed_on == 'CTS':
                self.get_proceed = self.get_cts
                print("CTS <- PROCEED")
            elif self.proceed_on == 'DSR':
                self.get_proceed = self.get_dsr
                print("DSR <- PROCEED")
            else:
                print("PROCEED not configured!")
            # serial port receiver
            self.allow_read.set()
            self.in_thread = SerInThread(self, hub)
            self.in_thread.start()
            # serial port sender
            self.out_thread = SerOutThread(self, hub, self.device_queue)
            self.out_thread.start()

    def stop(self):
        if self.in_thread:
            self.in_thread.stop()
            self.in_thread = None
        if self.out_thread:
            self.out_thread.stop()
            self.out_thread = None
        if self.serial:
            self.serial.close()
            self.serial = None

    def set_none(self, value:bool):
        pass

    def set_rts(self, value:bool):
        self.serial.rts = value

    def set_dtr(self, value:bool):
        self.serial.dtr = value

    def get_false(self) -> bool:
        return False

    def get_cts(self) -> bool:
        return self.serial.cts

    def get_dsr(self) -> bool:
        return self.serial.dsr

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
        return True
