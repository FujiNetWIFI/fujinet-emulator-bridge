# NetSIO

NetSIO is simple protocol to transmit signals and data bytes of Atari SIO (serial) port over network. UDP datagrams are used to exchange NetSIO messages between emulated Atari and NetSIO enabled peripherals, like FujiNet.

At the time of writing, no Atari emulator can speak directly NetSIO protocol. The middle component which can communicate with an emulator on one end and NetSIO protocol on the other end is needed - sort of bridge or hub. Such a middle component is `netsio-hub.py` (written in Python3). It listens to Altirra messages (via interface for Altirra's custom devices) and translates them into NetSIO messages (UDP datagrams) and vice versa.

## NetSIO protocol

| Message                                  | ID    | Parameters |
| ---                                      | ---   | ---|
| [Data byte](#data-byte)                  | 0x01  | B |
| [Data block](#data-block)                | 0x02  | B [B,...] |
| [Data byte and Sync request](#data-byte-and-sync-request) | 0x09  | B B |
| [Command OFF](#command-off)              | 0x10  |   |
| [Command ON](#command-on)                | 0x11  |   |
| [Command OFF and Sync request](#command-off-and-sync-request) | 0x18  | B |
| [Motor OFF](#motor-off)                  | 0x20  |   |
| [Motor ON](#motor-on)                    | 0x21  |   |
| [Proceed OFF](#proceed-off)              | 0x30  |   |
| [Proceed ON](#proceed-on)                | 0x31  |   |
| [Interrupt OFF](#interrupt-off)          | 0x40  |   |
| [Interrupt ON](#interrupt-on)            | 0x41  |   |
| TODO [Set CPB](#set-cpb)                 | 0x80  | H |
| TODO [Sync response](#sync-response)     | 0x81  | B B H |
| **Connection management**                |       |   |
| [Device disconnected](#device-disconnected) | 0xC0 |   |
| [Device connected](#device-connected)      | 0xC1  |   |
| [Ping request](#ping-request)            | 0xC2  |   |
| [Ping response](#ping-response)          | 0xC3  |   |
| [Alive request](#alive-request)          | 0xC4  |   |
| [Alive response](#alive-response)        | 0xC5  |   |
| **Notifications**                        |       |   |
| [Warm reset](#warm-reset)                | 0xFE  |   |
| [Cold reset](#cold-reset)                | 0xFF  |   |


With the exception to the ping and connect messages the device must be first connected to be able to participate in NetSIO communication (using `Device connected` message) .

### Data byte

| Data Byte |    |
| -- | -- |
| ID | 0x01 |
| Direction | Atari -> Device, Device -> Atari |
| Parameters | byte to transfer |

Transfers the SIO data byte from Atari to Device or from Device to Atari.

Used to transfer completion byte 'C' or checksum byte.

### Data block

| Data block |    |
| -- | -- |
| ID | 0x02 |
| Direction | Atari -> Device, Device -> Atari |
| Parameters | one or more bytes to transfer (up to 512) |

Transfers multiple data bytes from Atari to Device or from Device to Atari.

### Data byte and Sync request

| Data Byte |    |
| -- | -- |
| ID | 0x09 |
| Direction | Atari -> Device |
| Parameters | byte to transfer, sync request number |

Transfers the SIO data byte from Atari to Device together with the request to synchronize on next byte from Device to Atari. Emulator is paused waiting for Sync response.

Used on last byte (checksum) of SIO write command when Atari is sending data frame to the peripheral and expects the acknowledgment byte (ACK or NAK) to be delivered withing 850 us to 16 ms. The acknowledgment byte is send from device as Sync response. The emulation is resumed after Sync response is delivered to emulator. This pause-resume mechanism allows to extend the 16 ms requirement for the acknowledgment delivery.

### Command OFF

| Command OFF |    |
| -- | -- |
| ID | 0x10 |
| Direction | Atari -> Device |
| Parameters | none |

Command was de-asserted. Atari indicates to all connected devices the end of command frame.

Note: The command pin uses negative logic. Active command means low voltage on corresponding SIO pin and inactive command means high TTL voltage on pin. The pin is therefore marked as <span style="text-decoration:overline">COMMAND</span> or sometimes as /COMMAND.

Note: Currently not used, see [Command OFF and Sync request](#command-off-sync)

### Command ON

| Command ON |    |
| -- | -- |
| ID | 0x11 |
| Direction | Atari -> Device |
| Parameters | none |

Command was asserted. Atari indicates to all connected devices the start of command frame.

Note: The command pin uses negative logic. See Command OFF above.

### Command OFF and Sync request

| Command OFF and Sync request |    |
| -- | -- |
| ID | 0x18 |
| Direction | Atari -> Device |
| Parameters | none |

Command was de-asserted. Atari indicates to all connected devices the end of command frame together with the request to synchronize on next byte from Device to Atari. Emulator is paused waiting for Sync response.

When Atari is sending command frame to the peripheral it expects the acknowledgment byte (ACK or NAK) to be delivered withing 16 ms. The acknowledgment byte is send from device as Sync response. The emulation is resumed after Sync response is delivered to emulator. This pause-resume mechanism allows to extend the 16 ms requirement for the acknowledgment delivery.

### Motor OFF

| Motor OFF |    |
| -- | -- |
| ID | 0x20 |
| Direction | Atari -> Device |
| Parameters | none |

Cassette player motor off. Atari stops the cassette motor.

### Motor ON

| Motor OFF |    |
| -- | -- |
| ID | 0x21 |
| Direction | Atari -> Device |
| Parameters | none |

Cassette player motor on. Atari starts the cassette motor.

### Proceed OFF

### Proceed ON

| Proceed OFF |    |
| -- | -- |
| ID | 0x40 |
| Direction | Device -> Atari |
| Parameters | none |

| Proceed ON |    |
| -- | -- |
| ID | 0x41 |
| Direction | Device -> Atari |
| Parameters | none |

The device indicates to the Atari that it needs some attention. Used by FujiNet to indicate there is a data available for read.

Note: The proceed pin uses negative logic.

### Interrupt OFF

### Interrupt ON

| Interrupt OFF |    |
| -- | -- |
| ID | 0x30 |
| Direction | Device -> Atari |
| Parameters | none |

| Interrupt ON |    |
| -- | -- |
| ID | 0x31 |
| Direction | Device -> Atari |
| Parameters | none |

Similar to `proceed`, the device indicates to the Atari that the device needs some attention.

Note: The interrupt pin uses negative logic.

### Set CPB

| Data Byte |    |
| -- | -- |
| ID | 0x80 |
| Direction | Atari -> Device, Device -> Atari |
| Parameters | 2 bytes LSB+MSB, cycles per bit |

Indicates the data bitrate has changed. Next `Data byte` or `Fill buffer` will be transmitted at specified bitrate.

Note: For easy integration with Altirra the parameter uses Atari clock cycles per bit as a unit.

TODO: Replace cycles per bit with baud.

### Device disconnected

| Device disconnected |    |
| -- | -- |
| ID | 0xC0 |
| Direction | Device -> hub |
| Parameters | none |

The device was disconnected from NetSIO bus. It will not receive NetSIO messages anymore and messages from it will not be delivered to Atari anymore.

### Device connected

| Device connected |    |
| -- | -- |
| ID | 0xC1 |
| Direction | Device -> hub |
| Parameters | none |

The device was connected to NetSIO bus. NetSIO messages from Atari will be send to the device and messages from the device will be delivered to Atari.

### Ping request

### Ping response

| Ping request |    |
| -- | -- |
| ID | 0xC2 |
| Direction | Device -> hub |
| Parameters | none |

| Ping response |    |
| -- | -- |
| ID | 0xC3 |
| Direction | hub -> Device |
| Parameters | none |

Allows the device to test the availability of NetSIO hub. Similar to ICMP ping, it can be used to measure network round trip time between device and the hub.

### Alive request

### Alive response

| Alive request |    |
| -- | -- |
| ID | 0xC4 |
| Direction | Device -> hub |
| Parameters | none |

| Alive response |    |
| -- | -- |
| ID | 0xC5 |
| Direction | hub -> Device |
| Parameters | none |

The device informs the hub, that the device is still connected and interested into communication. The device must send the `Alive request` in regular intervals (every TBD). In turn, the hub must send `Alive response` to the device to let the device know the connection is still established.

### Warm reset

| Warm reset |    |
| -- | -- |
| ID | 0xFE |
| Direction | Atari -> device |
| Parameters | none |

Informs the connected device the emulated Atari did warm reset.

### Cold reset

| Cold reset |    |
| -- | -- |
| ID | 0xFF |
| Direction | Atari -> device |
| Parameters | none |

Informs the connected device the emulated Atari did cold reset, i.e. power cycle. The device might react to this message by resetting itself to simulate the situation when the device is powered from Atari.
