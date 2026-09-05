"""PAL Lighting local protocol — pure asyncio, no HA imports.

Implements the XLink UDP control path, verified against the live device
(Hi-Link HF-LPB100 bridge + PAL 4-switch MCU):

    1. handshake   (msg type 2)  -> sessionId
    2. probe       (msg type 3)  -> device marks the session ACTIVE
    3. status      (0xA3 pipe)   -> device pushes 0xA4 status to the session
    4. command     (0xA1 pipe)   -> the actual switch on/off

Two non-obvious rules, both learned the hard way (a full day of commands that
were ACKed but silently ignored):

- ALL steps MUST share one UDP socket (same source port). The device binds the
  session to the handshake's source port and drops pipes from any other port.
- The type-3 probe between handshake and command is MANDATORY — without it the
  device ACKs pipes but never forwards them to the lighting MCU.

The ACK `code` byte is not a success indicator (the working app commands get
code 0) — the only reliable feedback is the reply arriving at all.

XLink UDP wire format: header = [type<<4 | resp<<3 | proto][bodyLen:4BE],
pipe body = [sessionId:2][msgId:2][0x00][app frame].
"""

from __future__ import annotations

import asyncio
import hashlib
import random
import socket
import struct
import time
from dataclasses import dataclass

from .const import (
    CMD_SCENE,
    DATA_OFF,
    DATA_ON,
    DEVICE_UDP_PORT,
    HANDSHAKE_TIMEOUT_FIELD,
    ZONE_BYTE,
)

MSG_HANDSHAKE = 2
MSG_PROBE = 3
MSG_PIPE = 8

_HEADER_PROTO = 3  # low 3 bits of header byte[0] (SDK always ORs in 3)
_RECV_TIMEOUT = 3.0  # per-packet receive timeout, seconds


class PalProtocolError(Exception):
    """Device unreachable or answered with an error."""


@dataclass
class DeviceInfo:
    mac: str
    device_id: int
    mcu_version: int
    session_id: int


# ───────────────────────── wire helpers ─────────────────────────

def _header(msg_type: int, body_len: int, is_response: bool = False) -> bytes:
    b0 = ((msg_type & 0x0F) << 4) | (0x08 if is_response else 0) | _HEADER_PROTO
    return bytes([b0]) + struct.pack(">I", body_len)


def _decode(buf: bytes):
    """Return (msg_type, is_response, body) — raises on short/garbage."""
    if len(buf) < 5:
        raise PalProtocolError(f"short packet ({len(buf)}B): {buf.hex()}")
    msg_type = (buf[0] >> 4) & 0x0F
    is_response = ((buf[0] >> 3) & 1) == 1
    body_len = struct.unpack(">I", buf[1:5])[0]
    if len(buf) < 5 + body_len:
        raise PalProtocolError(f"truncated packet: {buf.hex()}")
    return msg_type, is_response, buf[5:5 + body_len]


def _accesskey_hash(access_key: int) -> bytes:
    """MD5 of the accessKey encoded as 4 little-endian bytes (SDK util.c.a)."""
    return hashlib.md5(struct.pack("<I", access_key & 0xFFFFFFFF)).digest()


class _MsgId:
    """SDK-style msg id counter: random start, +1 per message."""

    def __init__(self) -> None:
        self._n = random.randint(1000, 64000)

    def next(self) -> int:
        v = self._n & 0xFFFF
        self._n = (self._n + 1) & 0xFFFF
        return v


# ───────────────────────── packet builders ─────────────────────────

def _build_handshake(access_key: int, local_port: int, msgid: _MsgId, version: int) -> bytes:
    # v2 body: [version:1][MD5(accessKey LE4):16][localport:2][0x00][timeout:2] = 22 bytes
    body = struct.pack(">B", version) + _accesskey_hash(access_key) + \
        struct.pack(">HBH", local_port, 0x00, HANDSHAKE_TIMEOUT_FIELD)
    return _header(MSG_HANDSHAKE, len(body)) + body


def _build_probe(session_id: int) -> bytes:
    # body: [sessionId:2][0x00]
    body = struct.pack(">HB", session_id, 0x00)
    return _header(MSG_PROBE, len(body)) + body


def _build_pipe(session_id: int, msg_id: int, frame: bytes) -> bytes:
    # body: [sessionId:2][msgId:2][0x00][app frame]
    body = struct.pack(">HHB", session_id, msg_id, 0x00) + frame
    return _header(MSG_PIPE, len(body)) + body


def control_frame(pwd: int, data: int) -> bytes:
    """12-byte 0xA1 frame: [A1][pwd0][pwd1][zone][cmd][data][0*5][checksum]."""
    f = bytearray(12)
    f[0] = 0xA1
    f[1] = pwd & 0xFF
    f[2] = pwd & 0xFF
    f[3] = ZONE_BYTE
    f[4] = CMD_SCENE
    f[5] = data & 0xFF
    f[11] = sum(f[0:11]) & 0xFF
    return bytes(f)


def status_query_frame() -> bytes:
    """0xA3 status query (the app sends it right after the probe)."""
    f = bytearray(12)
    f[0] = 0xA3
    f[11] = sum(f[0:11]) & 0xFF
    return bytes(f)


# ───────────────────────── handshake reply parsing ─────────────────────────

def _parse_handshake(body: bytes) -> dict:
    """[code:1][version:1][mac:6][deviceId:4][mcuSoft:2][sessionId:2][skip:1]"""
    if len(body) < 11:
        return {"code": body[0] if body else -1, "version": body[1] if len(body) > 1 else 0}
    code, version = body[0], body[1]
    mac = body[2:8].hex().upper()
    device_id, mcu, session_id = struct.unpack(">IHH", body[8:16])
    return {
        "code": code,
        "version": version,
        "mac": mac,
        "device_id": device_id,
        "mcu_version": mcu,
        "session_id": session_id,
    }


# ───────────────────────── async transport ─────────────────────────

class _XlinkSocket:
    """One UDP socket = one session lifecycle (handshake -> probe -> pipes).

    Kept as a context manager so every command opens, negotiates, controls and
    closes — the same pattern validated live. UDP sessions expire anyway
    (handshake timeout field is 100), so a stateless-per-command client is both
    simplest and most robust.
    """

    def __init__(self, host: str) -> None:
        self._host = host
        self._sock: socket.socket | None = None
        self._msgid = _MsgId()

    async def __aenter__(self) -> _XlinkSocket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(False)
        sock.connect((self._host, DEVICE_UDP_PORT))
        self._sock = sock
        return self

    async def __aexit__(self, *exc) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    async def _recv_until(self, want_type: int, want_resp: bool) -> bytes:
        """Receive packets until one matches (type, resp); skip pushes/echoes."""
        loop = asyncio.get_running_loop()
        assert self._sock is not None
        deadline = time.monotonic() + _RECV_TIMEOUT
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise PalProtocolError(
                    f"no reply from device (wanted type {want_type}) — "
                    "check it is powered and on the network"
                )
            data = await asyncio.wait_for(loop.sock_recv(self._sock, 4096), timeout=left)
            msg_type, is_response, body = _decode(data)
            if msg_type == want_type and is_response == want_resp:
                return body

    async def _send(self, payload: bytes) -> None:
        loop = asyncio.get_running_loop()
        assert self._sock is not None
        await loop.sock_sendall(self._sock, payload)

    async def handshake(self, access_key: int) -> dict:
        """Handshake with version negotiation (device is protocol v2)."""
        assert self._sock is not None
        local_port = self._sock.getsockname()[1]
        tried: set[int] = set()
        for version in (2, 1, 3):  # 2 confirmed for the live device
            if version in tried:
                continue
            tried.add(version)
            await self._send(_build_handshake(access_key, local_port, self._msgid, version))
            body = await self._recv_until(MSG_HANDSHAKE, want_resp=True)
            info = _parse_handshake(body)
            if info.get("code") == 0:
                return info
            # code 2 = version mismatch; the reply names the real version — retry it
            reported = info.get("version", 0)
            if info.get("code") == 2 and reported and reported not in tried:
                await self._send(
                    _build_handshake(access_key, local_port, self._msgid, reported)
                )
                body = await self._recv_until(MSG_HANDSHAKE, want_resp=True)
                info = _parse_handshake(body)
                if info.get("code") == 0:
                    return info
                tried.add(reported)
        raise PalProtocolError(f"handshake rejected (code={info.get('code')})")

    async def probe(self, session_id: int) -> None:
        """Type-3 probe — MANDATORY: marks the session active in the device."""
        await self._send(_build_probe(session_id))
        # device answers with a type-5 [mac:6][status:1]; consume it
        await self._recv_type5()

    async def _recv_type5(self) -> None:
        loop = asyncio.get_running_loop()
        assert self._sock is not None
        deadline = time.monotonic() + _RECV_TIMEOUT
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                # probe reply is best-effort; the session is registered on send
                return
            try:
                data = await asyncio.wait_for(
                    loop.sock_recv(self._sock, 4096), timeout=left
                )
            except asyncio.TimeoutError:
                return
            msg_type, _resp, _body = _decode(data)
            if msg_type == 5:
                return

    async def _pipe(self, session_id: int, frame: bytes) -> bytes:
        """Send a pipe and return the device's ACK body (3 bytes: [msgId:2][code])."""
        msg_id = self._msgid.next()
        await self._send(_build_pipe(session_id, msg_id, frame))
        body = await self._recv_until(MSG_PIPE, want_resp=True)
        return body

    async def query_status(self, session_id: int) -> None:
        """0xA3 status query — part of the app's proven connect sequence."""
        await self._pipe(session_id, status_query_frame())

    async def send_control(self, session_id: int, frame: bytes) -> None:
        await self._pipe(session_id, frame)


# ───────────────────────── high-level API ─────────────────────────

async def async_probe_device(host: str, access_key: int) -> DeviceInfo:
    """Handshake + probe — used by the config flow to validate connectivity."""
    async with _XlinkSocket(host) as xs:
        info = await xs.handshake(access_key)
        await xs.probe(info["session_id"])
        return DeviceInfo(
            mac=info["mac"],
            device_id=info["device_id"],
            mcu_version=info["mcu_version"],
            session_id=info["session_id"],
        )


async def async_set_switch(
    host: str,
    access_key: int,
    password: int,
    switch_index: int,
    on: bool,
) -> None:
    """Turn switch_index (1..4) on/off. Full app sequence on a fresh socket."""
    if not 1 <= switch_index <= 4:
        raise PalProtocolError(f"switch index must be 1..4, got {switch_index}")
    data = DATA_ON[switch_index - 1] if on else DATA_OFF[switch_index - 1]
    frame = control_frame(password, data)
    async with _XlinkSocket(host) as xs:
        info = await xs.handshake(access_key)
        session_id = info["session_id"]
        await xs.probe(session_id)
        await xs.query_status(session_id)
        await xs.send_control(session_id, frame)