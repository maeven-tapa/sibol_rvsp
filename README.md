# Sibol Graduation RSVP

Django + SQLite kiosk-style graduation ticketing application.

```powershell
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open `http://127.0.0.1:8000/`. Staff users can access `/dashboard/` and Django admin at `/admin/`.

### Entry station

Open **Gate mode** as an administrator. Choose **Gate entry**, select the KMtronic USB serial port, choose a pulse duration, then open the station. Port discovery runs on the computer hosting Django. The USB/VCP driver must be installed there. Selecting a port only checks that it opens; it does not identify the model or switch a relay.

Supported protocol: KMtronic standard USB/VCP, 9600 baud, 8 data bits, no parity, 1 stop bit, on a controller with at least two relay channels. Regular tickets send `FF 01 01`, then `FF 01 00`; VIP sends `FF 02 01`, then `FF 02 00`. See [KMtronic's two-channel documentation](https://info.kmtronic.com/usb-relay-controller-two-channels.html). Confirm the board model uses this protocol before live entry. Successful serial writes do not confirm the gate's physical position.

**Reservation check** validates a pass without consuming it or sending relay commands. Both modes support a camera (localhost/HTTPS and camera permission), keyboard-emulating USB QR readers that send Enter, and manual entry. Camera decoding uses jsQR 1.4.0 from a CDN, so initial loading requires internet access.

Admission attempts are recorded before relay activation. Invalid, used, and previous-ceremony passes cannot pulse the controller. A failed or interrupted attempt is held for inspection and cannot automatically pulse again; inspect the controller and physical entry before any manual reconciliation. Admission records are visible in Django admin. Hardware tests were simulated; no live relay switching was performed during development.

The home photo uses `static/images/pic1.jpg` because `pic.jpg` was not present. The hero occupies the available page height when no ceremony is active.
