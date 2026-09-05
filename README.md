# PAL Lighting HACS integration for Home Assistant

Custom Home Assistant integration for **PAL Lighting** 4-switch WiFi
controllers (`com.irainxun.pallight`, the XLink/Aiyunxun white-label platform).
The vendor provides no local API; this integration drives the same local UDP
path the official app uses when the device is on your LAN — **no cloud account,
no internet, fully local**.

> **Interoperability, not abuse.** This integration exists so the owner of a
> controller can drive its 4 switches from Home Assistant. It speaks the
> device's LAN protocol only (UDP 5987); nothing here touches the vendor cloud.

## What it gives you

- **4 switch entities** (`Switch 1`–`Switch 4`) matching the app's 4-button
  remote. Rename them freely in HA (e.g. Switch 2 → "Spa pump").
- Entities are **optimistic** (assumed state): the device reports no readable
  switch state — the official app behaves exactly the same way, remembering
  only what it last sent. The last commanded state **survives HA restarts**
  (restore state), so a switch that was on before a restart comes back as on.
- **Reachability tracking**: a background probe (handshake + probe, default
  every 20 s; configurable at setup, 0 disables) marks the switches
  `unavailable` when the controller stops answering and restores them when it
  answers again. A toggle while the device is down raises an error — it never
  silently pretends to succeed.
- Device registry entry with the MAC, MCU firmware version and model
  discovered during setup validation.

## How it talks to the device (protocol notes)

Control is the 0xA1 frame `[A1][pwd0][pwd1][0x04][0x03][data]…[checksum]`
carried over the XLink UDP pipe protocol on port 5987. Switch N (1-based):
**OFF = data `2(N-1)`, ON = data `2(N-1)+1`** — so sw1 `00/01`, sw2 `02/03`,
sw3 `04/05`, sw4 `06/07`.

Every command runs the app's full connect sequence, on a **single UDP socket**:

1. **handshake** (msg type 2) with `MD5(accessKey as 4 little-endian bytes)`
2. **probe** (msg type 3) — mandatory; without it the device ACKs commands but
   never forwards them to the relay MCU
3. **status query** (0xA3)
4. the **command pipe** (msg type 8)

Two hard-won gotchas encoded in `protocol.py`: the handshake and all pipes must
share one source port (the device binds the session to it), and the probe step
is what activates the session. The device's ACK `code` byte is meaningless —
a working command gets `code 0`.

## Install (HACS)

1. HACS → Integrations → ⋮ → **Custom repositories** → add this repo URL,
   category *Integration*.
2. Install **PAL Lighting**, restart Home Assistant.
3. Settings → Devices & Services → **Add Integration** → *PAL Lighting*.
4. Enter the controller's IP (e.g. `192.168.20.170`). Advanced fields:
   - **Access key** — factory default `123456789`
   - **Password byte** — default `117` (0x75). Both frame password bytes are
     set to this value; 117/117 is what shipping units use.

Setup validates connectivity (handshake + probe) before creating the entry,
and the controller's MAC becomes the stable unique id.

## Caveats

- The device keeps a long-lived TCP connection to the vendor cloud
  (`cm.xlink.cn:23778`) and mirrors commands there. Blocking that at the
  firewall does **not** affect local control — this integration never needs it.
- Switch state is not readable; if you toggle from the physical app/other
  sources, HA won't know until its next command.
- One entry per controller.

## License

MIT.