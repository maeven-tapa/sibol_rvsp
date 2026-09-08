"""KMtronic standard USB VCP binary protocol, 9600 baud, 8N1.

Reference: https://info.kmtronic.com/usb-relay-controller-two-channels.html
Commands are writes, not a physical gate position acknowledgement.
"""
import time
from contextlib import contextmanager
from threading import Lock
import serial
from serial.tools import list_ports

_lock = Lock()


class RelayError(Exception):
    pass


def ports():
    return [{'device': p.device, 'description': p.description or 'Serial port'} for p in list_ports.comports()]


@contextmanager
def connection(port):
    if port not in {p['device'] for p in ports()}:
        raise RelayError('The selected USB port is disconnected. Return to setup and refresh ports.')
    if not _lock.acquire(blocking=False):
        raise RelayError('The relay is busy. Please wait for the current admission.')
    try:
        with serial.Serial(port, baudrate=9600, bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE, timeout=0.5, write_timeout=1, rtscts=False, dsrdtr=False) as device:
            yield device
    except (serial.SerialException, OSError) as exc:
        raise RelayError('Cannot communicate with the USB relay. Check its cable, driver, and port selection.') from exc
    finally:
        _lock.release()


def pulse(device, channel, duration):
    if channel not in (1, 2) or not 0.2 <= duration <= 5:
        raise RelayError('Invalid relay configuration.')
    def send(state):
        if device.write(bytes([0xFF, channel, state])) != 3:
            raise RelayError('Incomplete relay command. Inspect the controller before admitting this ticket again.')
        device.flush()
    try:
        send(1)
        time.sleep(duration)
    finally:
        # Always attempt OFF, including partial writes or an ON failure.
        send(0)
