# fujinet-emulator-bridge

* fujinet-bridge - reflects SIO bus from the emulator to FujiNet and back.
* altirra-custom-device - The custom .atdevice to allow fujinet-bridge to connect to Altirra.



High level diagram:

![Emulator bridge high level diagram](emulator-bridge.png)

The top part of the diagram shows generic building blocks. At the bottom part the current implementation is depicted.

[Altirra](https://virtualdub.org/altirra.html) is a popular Atari emulator which runs under Windows. Linux and macOS users can run it with Wine. Custom devices can be "connected to Atari" in Configure System / Peripherals / Devices dialog. `netsio.atdevice` is  a device which connects Altirra with NetSIO hub.

The role of NetSIO hub is to rely data and signals from emulated SIO bus to all connected devices. NetSIO hub is written in Python3 and it must be running on the same computer as Altirra. It is built on top of Custom Device Server which is part of Altirra emulator.

Signals and data on SIO bus are translated and sent over network as UDP datagrams. This is handled by  [NetSIO](netsio.md) protocol.

## Installing

Get copy of this repository. Use `git clone` or Download ZIP from GitHub and unzip downloaded file.

## Running

- Start NetSIO hub

  Python 3 is needed and must be already installed. The command `python -V` (or `python3 -V`) should report Python version 3.x

  Open command prompt and change to the directory with obtained repository. From there enter subdirectory named `fujinet-bridge`. Start NetSIO hub with `python -m netsiohub` (or `python3 -m netsiohub` if `python` command is not Python 3 in your environment).
  
- Connect Altirra with NetSIO hub

  In Altirra: System > Configure System ... under Peripherals / Devices add Custom device (scroll down) and navigate to `altirra-custom-device` folder. Here select the `netsio.atdevice`.
  
  More detailed [instructions with some pictures](https://github.com/a8jan/fujinet-pc-launcher/blob/master/Install.md#4-connect-altirra-with-fujinet). Check the steps Connect Altirra with FujiNet and on.

- Connect FujiNet with NetSIO hub

  In FujiNet web interface, in Emulator settings (at the page bottom) enable SIO over Network option and fill in host name or IP address of computer running Altirra and hub. Save settings.

- To boot emulated Atari from FujiNet (optional)

  * First, `D1:` must be removed from Altirra: File > Detach Disk > Drive 1
  * Ensure Fast boot feature is disabled: System > Configure System > Acceleration > uncheck Fast boot in OS acceleration
  * Reboot the emulated Atari with `Shift+F5`.

- It is possible to use emulated disk devices in Altirra together with FujiNet. It's like to run FujiNet with other disk drives connected. Some disks can be from FujiNet, other disks can be emulated by Altirra. Take care to use different drive numbers.

