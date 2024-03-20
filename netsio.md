# NetSIO

NetSIO is simple protocol to transmit signals and data bytes of Atari SIO (serial) port over network. UDP datagrams are used to exchange NetSIO messages between emulated Atari and NetSIO enabled peripherals, like FujiNet.

At the time of writing, no Atari emulator can speak directly NetSIO protocol. The middle component which can communicate with an emulator on one end and NetSIO protocol on the other end is needed - sort of bridge or hub. Such a middle component is `netsio-hub.py` (written in Python3). It listens to Altirra messages (via interface for Altirra's custom devices) and translates them into NetSIO messages (UDP datagrams) and vice versa.

## NetSIO protocol

| Message                                     | ID    | Parameters |
| ---                                         | ---   | ---|
| [Data byte](#data-byte)                     | 0x01  | data_byte: uint8 |
| [Data block](#data-block)                   | 0x02  | byte_array: uint8[] |
| [Data byte and Sync request](#data-byte-and-sync-request) | 0x09  | data_byte: uint8, sync_number: uint8 |
| [Command ON](#command-on)                   | 0x11  |   |
| [Command OFF](#command-off)                 | 0x10  |   |
| [Command OFF and Sync request](#command-off-and-sync-request) | 0x18  | sync_number: uint8 |
| [Motor ON](#motor-on)                       | 0x21  |   |
| [Motor OFF](#motor-off)                     | 0x20  |   |
| [Proceed ON](#proceed-on)                   | 0x31  |   |
| [Proceed OFF](#proceed-off)                 | 0x30  |   |
| [Interrupt ON](#interrupt-on)               | 0x41  |   |
| [Interrupt OFF](#interrupt-off)             | 0x40  |   |
| [Speed change](#speed-change)               | 0x80  | baud: uint32 |
| [Sync response](#sync-response)             | 0x81  | sync_number: uint8, ack_type: uint8, ack_byte: uint8, write_size: uint16 |
| **Connection management**                   |       |   |
| [Device connected](#device-connected)       | 0xC1  |   |
| [Device disconnected](#device-disconnected) | 0xC0  |   |
| [Ping request](#ping-request)               | 0xC2  |   |
| [Ping response](#ping-response)             | 0xC3  |   |
| [Alive request](#alive-request)             | 0xC4  |   |
| [Alive response](#alive-response)           | 0xC5  |   |
| [Credit status](#credit-status)             | 0xC6  |   |
| [Credit update](#credit-update)             | 0xC7  |   |
| **Notifications**                           |       |   |
| [Warm reset](#warm-reset)                   | 0xFE  |   |
| [Cold reset](#cold-reset)                   | 0xFF  |   |


With the exception to the ping the device must be first connected ([Device connected](#device-connected)) to be able to participate in NetSIO communication.

### Data byte

| Data Byte |    |
| -- | -- |
| ID | 0x01 |
| Direction | Atari -> Device, Device -> Atari |
| Parameters | data_byte: uint8 - byte to transfer |

Transfers the SIO data byte from Atari to Device or from Device to Atari.

Used to, but not limited to, transfer completion byte 'C' or checksum byte.

### Data block

| Data block |    |
| -- | -- |
| ID | 0x02 |
| Direction | Atari -> Device, Device -> Atari |
| Parameters | byte_array: uint8[] - one or more bytes to transfer (up to 512) |

Transfers multiple data bytes from Atari to Device or from Device to Atari.

### Data byte and Sync request

| Data Byte and Sync request |    |
| -- | -- |
| ID | 0x09 |
| Direction | Atari -> Device |
| Parameters | data_byte: uint8 - byte to transfer |
|            | sync_number: uint8 - sync request number |

Transfers the SIO data byte from Atari to Device together with the request to synchronize on next byte from Device to Atari. Atari emulation is paused waiting for Sync response.

Used on last byte (checksum) of SIO write command when Atari is sending data frame to the peripheral and expects the acknowledgment byte (ACK or NAK) to be delivered withing 850 us to 16 ms. The acknowledgment byte will be sent from device as Sync response. Atari emulation is resumed after Sync response is delivered to the emulator. This pause-resume mechanism allows to extend the 16 ms requirement for the acknowledgment delivery.

`sync request number` is incremented with every Sync request sent. It is used to match corresponding [Sync response](#sync-response).

### Command ON

| Command ON |    |
| -- | -- |
| ID | 0x11 |
| Direction | Atari -> Device |
| Parameters | none |

Command was asserted. Atari indicates to all connected devices the start of command frame.

Note: The command pin uses negative logic. Active command means low voltage on corresponding SIO pin and inactive command is high on SIO pin.

### Command OFF

| Command OFF |    |
| -- | -- |
| ID | 0x10 |
| Direction | Atari -> Device |
| Parameters | none |

Command was de-asserted. Atari indicates to all connected devices the end of command frame.

Note: The command pin uses negative logic.

Note: Currently not used, see [Command OFF and Sync request](#command-off-and-sync-request)

### Command OFF and Sync request

| Command OFF and Sync request |    |
| -- | -- |
| ID | 0x18 |
| Direction | Atari -> Device |
| Parameters | sync_number: uint8 - sync request number |

Command was de-asserted. Atari indicates to all connected devices the end of command frame together with the request to synchronize on next byte from Device to Atari. Atari emulation is paused waiting for Sync response.

When Atari is sending command frame to the peripheral it expects the acknowledgment byte (ACK or NAK) to be delivered withing 16 ms. The acknowledgment byte will be sent from device as Sync response. Atari emulation is resumed after Sync response is delivered to the emulator. This pause-resume mechanism allows to extend the 16 ms requirement for the acknowledgment delivery.

`sync request number` is incremented with every Sync request sent. It is used to match corresponding [Sync response](#sync-response).

### Motor ON

| Motor OFF |    |
| -- | -- |
| ID | 0x21 |
| Direction | Atari -> Device |
| Parameters | none |

Cassette player motor on. Atari starts the cassette motor.

### Motor OFF

| Motor OFF |    |
| -- | -- |
| ID | 0x20 |
| Direction | Atari -> Device |
| Parameters | none |

Cassette player motor off. Atari stops the cassette motor.

### Proceed ON

### Proceed OFF

| Proceed ON |    |
| -- | -- |
| ID | 0x41 |
| Direction | Device -> Atari |
| Parameters | none |

| Proceed OFF |    |
| -- | -- |
| ID | 0x40 |
| Direction | Device -> Atari |
| Parameters | none |

The device indicates to the Atari that it needs some attention. Used by FujiNet to indicate there is a data available for read.

Note: The proceed pin uses negative logic.

### Interrupt ON

### Interrupt OFF

| Interrupt ON |    |
| -- | -- |
| ID | 0x31 |
| Direction | Device -> Atari |
| Parameters | none |

| Interrupt OFF |    |
| -- | -- |
| ID | 0x30 |
| Direction | Device -> Atari |
| Parameters | none |

Similar to `proceed`, the device indicates to the Atari that the device needs some attention.

Note: The interrupt pin uses negative logic.

### Speed change

| Speed change |    |
| -- | -- |
| ID | 0x80 |
| Direction | Atari -> Device, Device -> Atari |
| Parameters | baud: uint32 - 4 bytes little-endian baud |

Indicates the outgoing data rate has changed. Next [Data byte](#data-byte) or [Data block](#data-block) will be transmitted at specified rate.

The speed has an effect when transferring data to emulated Atari. It will appear as Data bits will "arrive" to SIO Data In pin at specified rate.

In opposite direction, when NetSIO device is receiving data, the bitrate of data is just complementary information. However this information can be used to simulate errors in case the device is currently expecting data to arrive at different bitrate. E.g. this is used by FujiNet to toggle speed between standard 19200 and high speed when specific error threshold is reached.

### Sync response

| Sync response |    |
| -- | -- |
| ID | 0x81 |
| Direction | Device -> Atari |
| Parameters | sync_number: uint8 - sync request number |
|            | ack_type: uint8 - acknowledgment type |
|            | ack_byte: uint8 - acknowledgment byte |
|            | write_size: uint16 - LSB+MSB write size next sync |

Response to [Command OFF and Sync request](#command-off-and-sync-request) or [Data byte and Sync request](#data-byte-and-sync-request). Atari emulation is paused after sending sync request and it's waiting for Sync response. After Sync response is delivered the emulation is resumed.

The purpose of Sync request-response mechanism is to allow SIO acknowledgment (ACK/NAK) in time delivery. There are two scenarios when ACK/NAK is expected. First scenario, anytime when Atari sends command frame to all connected devices, it expects acknowledgment byte from device which will handle the command. Second scenario is for SIO write command, when Atari sends data frame (data part of SIO write command), it expects the acknowledgment of successful delivery. In both cases the acknowledgment delivery is expected no later then 16 ms after command frame or data frame was sent by Atari. With emulation pause and resume it's possible to meet this timing requirement even with NetSIO devices connected over latent networks.

* `sync request number` matches `sync request number` from Sync request.

* `acknowledgment type`

  0 = Empty acknowledgment (device is not interested into this command), `acknowledgment byte` and `write size next sync` are ignored. This allows to resume the emulation in case there is no acknowledgment from any device.

  1 = Valid acknowledgment, `acknowledgment byte` will be sent to Atari.

* `acknowledgment byte` is a byte the Atari is waiting for. For standard SIO it is ACK (65, 'A') or NAK (78, 'N').

* `write size next sync` this is used to "plan" next Sync request for SIO write command.

  non zero value = current command is SIO write and next acknowledgment (via Sync request-response) is expected after this amount of bytes will be sent from Atari to the device.

  0 = do not "plan" next sync

### Device connected

| Device connected |    |
| -- | -- |
| ID | 0xC1 |
| Direction | Device -> hub |
| Parameters | none |

The device was connected to NetSIO bus. NetSIO messages from Atari will be sent to the device and messages from the device will be delivered to Atari.

### Device disconnected

| Device disconnected |    |
| -- | -- |
| ID | 0xC0 |
| Direction | Device -> hub |
| Parameters | none |

The device was disconnected from NetSIO bus. It will not receive NetSIO messages anymore and messages from it will not be delivered to Atari anymore.

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

### Credit status

### Credit update

| Credit status |    |
| -- | -- |
| ID | 0xC6 |
| Direction | Device -> hub |
| Parameters | credit: uint8 - remaining credit on device |

| Credit update |    |
| -- | -- |
| ID | 0xC7 |
| Direction | hub -> Device |
| Parameters | credit: uint8 - credit given to device |

Device uses a credit system for sending NetSIO messages which should be processed by emulator (data bytes, proceed, interrupt). Processing of these messages on emulator can take some time (e.g. if emulator emulates POKEY receiving a byte). When such a message is sent one credit is consumed. If device is out of credit it informs the hub and then waits for additional credit from hub before sending the message. This mechanism prevents the queue on emulator side to be overfilled with incoming messages, whereas it allows few messages to be waiting in that queue for processing.

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
