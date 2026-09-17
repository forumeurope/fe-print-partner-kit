#!/usr/bin/env python3
"""fake-partner-hub.py: a stand-in for the FE print hub, for developing a print partner client.

It answers the same routes, with the same JSON, as a real hub in print partner
mode, and sends the same UDP datagrams. All data is made up. Nothing is printed.

Python 3.10 or newer, standard library only. Windows, macOS and Linux.

    python fake-partner-hub.py                  start it on port 8631
    python fake-partner-hub.py --every 20       also send a sample badge every 20 s
    python fake-partner-hub.py --mode manage    answer 409, as a hub not in partner mode
    python fake-partner-hub.py --mode locked    answer 503, as a hub whose desk isn't started

Then run your client against 127.0.0.1, or open http://127.0.0.1:8631/ and
press "Send a sample print".

At start it holds six badges: three waiting (one of them never announced, so
only the waiting list finds it), one cancelled (410, never listed), and two
that try to make your client print a badge twice:

  * Robin Retry   collect it and the desk "asks again": the same badge comes
                  back under a NEW print id with the SAME jobKey, and is
                  announced again. Print it once.
  * Ash Repeat    stays on the waiting list after you collect it, the way a
                  client that restarts is offered a badge it already has.
                  Print it once.

Each badge is announced three times, as a real hub does, and a badge goes to
ONE client: a second one asking for it gets 409 (send X-Print-Collector so the
hub can tell your client from somebody else's, and let you re-ask for your own).
Sam Sample is a reprint — a new job key, so it IS a new badge and IS printed.

Unlike a real hub, badges wait until collected, so you can start your client later.

A sample badge behaves exactly like a real one: it is announced, waits 10
seconds for you, and is cancelled (410) if you didn't collect it.

Differences from a real hub: nothing is kept after a restart, the picture is a
plain placeholder, and datagrams also go to 127.0.0.1.
"""

import sys

if sys.version_info < (3, 10):
    sys.exit("This needs Python 3.10 or newer. You have "
             f"{sys.version.split()[0]}. Get it from https://www.python.org/downloads/")

import argparse
import base64
import datetime
import json
import signal
import socket
import struct
import threading
import time
import uuid
import zlib
import socketserver
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DOORBELL_PORT = 8632
RINGS = 3
RING_SPACING = 0.2  # seconds
PICKUP_WAIT = 10.0  # seconds a desk waits
KEEP = 600.0  # seconds a badge is kept
HUB_NAME = "Stand-in Hub"

NOT_PARTNER = ("This hub is not in print partner mode, so there is nothing to pick up. "
               "Ask the FE team to switch it on from their app.")
LOCKED = ("This desk hasn't started yet, so badges cannot be handed to the print partner. "
          "Open the FE app on a desk device and tap Start the desk.")
CANCELLED = "This print was cancelled because it wasn't collected in time."
NOT_FOUND = ("There is no print with this id on this hub. Prints are kept for 10 minutes; "
             "ask the desk to print it again.")
NOT_PICKED_UP = "Not picked up by the print partner. Check their system is on this network."
ALREADY_COLLECTED = ("Another print partner client on this network already collected this badge, so it "
                     "is being printed. Run one collector, or give each one its own X-Print-Collector id.")
COLLECTOR_HEADER = "X-Print-Collector"

EVENT = {"id": "9a0e3c1d-2b4f-4e6a-8c7d-1f2e3d4c5b6a", "name": "Example Summit 2026"}

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(errors="backslashreplace")
    except (AttributeError, ValueError):
        pass


def log(msg):
    print(f"{time.strftime('%H:%M:%S')} stand-in: {msg}", flush=True)


def utc_now():
    # The hub's format: ISO 8601, UTC, microseconds, Z.
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def make_png(width=816, height=512, border=6):
    """A black-and-white placeholder badge (8-bit RGB, like the hub's): white, black frame."""

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    black, white = b"\x00\x00\x00", b"\xff\xff\xff"
    edge = b"\x00" + black * width
    middle = b"\x00" + black * border + white * (width - 2 * border) + black * border
    raw = b"".join(edge if y < border or y >= height - border else middle for y in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


PNG_B64 = base64.b64encode(make_png()).decode("ascii")
LOGO_B64 = base64.b64encode(make_png(120, 60, 4)).decode("ascii")

# The layout the hub sends for the standard 102 x 64 mm label: mm from the printable area's corner.
LAYOUT = {
    "areaXMm": 3, "areaYMm": 3, "areaWidthMm": 96, "areaHeightMm": 58, "authored": False,
    "elements": [
        {"kind": "Name", "xMm": 2.5, "yMm": 2.5, "widthMm": 59.38, "heightMm": 9.7875,
         "sizeMm": 7.25, "bold": True, "align": "Left", "maxLines": 2},
        {"kind": "NameLocal", "xMm": 2.5, "yMm": 12.2875, "widthMm": 59.38, "heightMm": 7.3515,
         "sizeMm": 5.655, "bold": False, "align": "Left", "maxLines": 1},
        {"kind": "Organisation", "xMm": 2.5, "yMm": 25.671, "widthMm": 59.38, "heightMm": 6.032,
         "sizeMm": 4.64, "bold": False, "align": "Left", "maxLines": 1},
        {"kind": "BadgeType", "xMm": 2.5, "yMm": 49.004, "widthMm": 59.38, "heightMm": 6.496,
         "sizeMm": 4.64, "bold": True, "align": "Left", "maxLines": 1},
        {"kind": "Qr", "xMm": 64.38, "yMm": 14.44, "widthMm": 29.12, "heightMm": 29.12,
         "sizeMm": 29.12, "bold": False, "align": "Left", "maxLines": 1},
    ],
}


def make_print(*, test, name, name_local=None, organisation=None, job_title=None, badge_type="Delegate",
               serial=None, registration=True, reprint=False, reason=None, desk="Desk 1", event=True,
               footer=None, text_color="#000000", job_key=None, print_id=None):
    print_id = print_id or str(uuid.uuid4())
    return {
        "id": print_id,
        "time": utc_now(),
        "desk": desk,
        "test": test,
        "badge": {
            "name": name,
            "nameLocal": name_local,
            "organisation": organisation,
            "jobTitle": job_title,
            "type": badge_type,
            "qr": f"FE1:B:{serial}" if serial else "FE1:D:CALIBRATION",
            "serial": serial,
            "registrationId": str(uuid.uuid4()) if registration else None,
            "reprint": reprint,
            "reason": reason if reprint else None,
        },
        "event": EVENT if event else None,
        "design": {
            "medium": "Label102x64",
            "showName": True,
            "showOrganisation": True,
            "showJobTitle": False,
            "showType": True,
            "showQr": True,
            "showLogo": event,
            "footerText": footer,
            "textColor": text_color,
            "whiteAreaXMm": None,
            "whiteAreaYMm": None,
            "whiteAreaWidthMm": None,
            "whiteAreaHeightMm": None,
            "qrSizeMm": None,
            "layout": LAYOUT,
            "logo": {"contentType": "image/png", "base64": LOGO_B64} if event else None,
        },
        "size": {"widthMm": 102, "heightMm": 64},
        "image": {"contentType": "image/png", "dpi": 203, "widthPx": 816, "heightPx": 512, "base64": PNG_B64},
        # The desk's badge behind this offer. The same across a desk retry, even
        # when the retry is offered under a new id: what a partner dedupes on.
        "jobKey": job_key or print_id,
    }


def sample_print():
    """What a real hub's "Send a sample print" hands over."""
    return make_print(test=True, name="Desk 1", organisation="Sample badge — not a real event",
                      badge_type="TEST", registration=False, desk="Bench page", event=False,
                      footer="bench sample", text_color=None)


class Hub:
    def __init__(self, mode, host, port):
        self.mode = mode  # broadcast | manage | locked
        self.host = host
        self.port = port
        self.jobs = {}  # id -> {"print", "created", "picked", "withdrawn", "event"}
        self.last_pickup = None
        self.lock = threading.Lock()

    def add(self, p, withdrawn=False, sticky=False):
        """sticky: stays on the waiting list after it is collected, the way a
        client that restarts sees a badge offered to it a second time. A client
        that keeps a record of what it printed saves it once anyway."""
        with self.lock:
            self.jobs[p["id"]] = {"print": p, "created": time.monotonic(), "picked": None,
                                  "withdrawn": withdrawn, "sticky": sticky, "by": None,
                                  "event": threading.Event()}

    def sweep(self):
        now = time.monotonic()
        for k in [k for k, j in self.jobs.items() if now - (j["picked"] or j["created"]) >= KEEP]:
            del self.jobs[k]

    def waiting(self):
        with self.lock:
            self.sweep()
            items = [j for j in self.jobs.values()
                     if (not j["picked"] or j["sticky"]) and not j["withdrawn"]]
            return [j["print"] for j in sorted(items, key=lambda j: j["created"])]

    def pick_up(self, print_id, collector=None):
        """(job, taken). taken is True when somebody ELSE already collected it:
        one badge goes to one client, and the client that took it may ask again."""
        with self.lock:
            self.sweep()
            j = self.jobs.get(print_id)
            if j is None or j["withdrawn"]:
                return j, False
            if not j["picked"]:
                j["picked"] = time.monotonic()
                j["by"] = collector
                self.last_pickup = utc_now()
                j["event"].set()
                log(f"collected {print_id} by {collector or 'a client with no id'}")
                return j, False
            taken = not collector or j["by"] != collector
            if taken:
                log(f"refused {print_id} to {collector or 'a client with no id'}: already collected")
            return j, taken

    def after_pickup(self, j):
        """A badge marked "retry" is offered ONE more time, under a new print id
        and the same job key, and announced again — the desk asking a second
        time because it never heard back. A partner that keys on the job key
        prints it once; one that keys on the print id alone prints it twice.
        """
        p = j["print"]
        if not j.pop("retry", False):
            return
        again = dict(p, id=str(uuid.uuid4()), time=utc_now())
        self.add(again)
        log(f"desk retry: {p['badge']['name']} offered again as {again['id']} "
            f"(job key {again['jobKey']}) — it must NOT be printed twice")
        threading.Thread(target=self.ring, args=(again,), daemon=True).start()

    def withdraw(self, print_id):
        """False when it was collected first."""
        with self.lock:
            j = self.jobs[print_id]
            if j["picked"]:
                return False
            j["withdrawn"] = True
            return True

    def ring(self, p):
        bell = json.dumps({
            "fehub": 1, "type": "print", "id": p["id"], "hub": HUB_NAME,
            "pickup": f"http://{self.host}:{self.port}/v1/prints/{p['id']}",
            "time": p["time"], "test": p["test"],
        }, separators=(",", ":")).encode("utf-8")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            for n in range(RINGS):
                if n:
                    time.sleep(RING_SPACING)
                for dest in ("255.255.255.255", "127.0.0.1"):
                    try:
                        sock.sendto(bell, (dest, DOORBELL_PORT))
                    except OSError as e:
                        log(f"datagram to {dest} not sent: {e}")
        finally:
            sock.close()

    def send_sample(self):
        """A desk print: announce, wait 10 s, cancel if not collected."""
        p = sample_print()
        self.add(p)
        log(f"sample {p['id']} announced; waiting {PICKUP_WAIT:g}s")
        threading.Thread(target=self.ring, args=(p,), daemon=True).start()
        picked = self.jobs[p["id"]]["event"].wait(PICKUP_WAIT)
        if not picked and not self.withdraw(p["id"]):
            picked = True
        if not picked:
            log(f"sample {p['id']} not collected: cancelled (410 from now on)")
        return {"pickedUp": picked, "message": None if picked else NOT_PICKED_UP}


PAGE = """<!doctype html><meta charset="utf-8"><title>Stand-in hub</title>
<style>body{font:16px system-ui,sans-serif;margin:2rem;max-width:40rem}button{font:inherit;padding:.4rem .8rem}</style>
<h1>Stand-in hub</h1>
<p>Mode: <b id="mode">?</b> <button onclick="mode('broadcast')">Print partner mode</button>
<button onclick="mode('manage')">Not in partner mode (409)</button></p>
<p><button onclick="sample()">Send a sample print</button> <span id="out"></span></p>
<p id="stat"></p>
<script>
async function show(){const m=await (await fetch('/v1/bench/print-mode')).json();
document.getElementById('mode').textContent=m.mode;
document.getElementById('stat').textContent=(m.lastPickupAt?'Last collected '+m.lastPickupAt:'Nothing collected yet')+'. Waiting: '+m.waitingForPickup;}
async function mode(m){await fetch('/v1/bench/print-mode',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:m})});show();}
async function sample(){const o=document.getElementById('out');o.textContent='Waiting up to 10 s...';
const r=await (await fetch('/v1/bench/sample-print',{method:'POST'})).json();
o.textContent=r.pickedUp?'Collected by your system.':(r.message||r.detail);show();}
show();setInterval(show,3000);
</script>"""


def make_handler(hub):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def send(self, status, body, ctype="application/json; charset=utf-8", extra=None):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def problem(self, status, title, detail):
            section = "15.6.4" if status == 503 else f"15.5.{status - 399}"
            self.send(status, {"type": f"https://tools.ietf.org/html/rfc9110#section-{section}",
                               "title": title, "status": status, "detail": detail},
                      "application/problem+json")

        def partner_ready(self):
            if hub.mode == "manage":
                self.problem(409, "Not in print partner mode", NOT_PARTNER)
                return False
            if hub.mode == "locked":
                self.problem(503, "The desk hasn't started", LOCKED)
                return False
            return True

        def mode_view(self):
            return {"mode": "manage" if hub.mode == "manage" else "broadcast", "broadcastPort": DOORBELL_PORT,
                    "lastPickupAt": hub.last_pickup, "waitingForPickup": len(hub.waiting())}

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/":
                self.send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/v1/bench/print-mode":
                self.send(200, self.mode_view())
            elif path == "/v1/status":
                v = self.mode_view()
                self.send(200, {"hubName": HUB_NAME, "printMode": v["mode"],
                                "lastPickupAt": v["lastPickupAt"], "waitingForPickup": v["waitingForPickup"]})
            elif path == "/v1/prints":
                if self.partner_ready():
                    host = self.headers.get("Host") or f"{hub.host}:{hub.port}"
                    self.send(200, {"waiting": [
                        {"id": p["id"], "jobKey": p["jobKey"], "time": p["time"], "test": p["test"],
                         "pickup": f"http://{host}/v1/prints/{p['id']}"} for p in hub.waiting()]})
            elif path.startswith("/v1/prints/"):
                if not self.partner_ready():
                    return
                try:
                    print_id = str(uuid.UUID(path.rsplit("/", 1)[-1]))
                except ValueError:
                    self.send(404, b"", "text/plain")
                    return
                j, taken = hub.pick_up(print_id, (self.headers.get(COLLECTOR_HEADER) or "").strip() or None)
                if j is None:
                    self.problem(404, "No such print", NOT_FOUND)
                elif j["withdrawn"]:
                    self.problem(410, "Print cancelled", CANCELLED)
                elif taken:
                    self.problem(409, "Already collected", ALREADY_COLLECTED)
                else:
                    self.send(200, j["print"], extra={"Cache-Control": "no-store"})
                    hub.after_pickup(j)
            else:
                self.send(404, b"", "text/plain")

        def do_PUT(self):
            if self.path != "/v1/bench/print-mode":
                return self.send(404, b"", "text/plain")
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                mode = str(body.get("mode", "")).strip().lower()
            except (ValueError, AttributeError):
                mode = ""
            if mode not in ("manage", "broadcast"):
                return self.problem(400, "Unknown mode", "mode must be \"manage\" or \"broadcast\".")
            hub.mode = mode
            log(f"mode is now {mode}")
            self.send(200, self.mode_view())

        def do_POST(self):
            if self.path != "/v1/bench/sample-print":
                return self.send(404, b"", "text/plain")
            if hub.mode != "broadcast":
                return self.problem(409, "Not in print partner mode",
                                    "This hub is not in print partner mode, so there is no partner to send a test to.")
            self.send(200, hub.send_sample())

    return Handler


class Server(ThreadingHTTPServer):
    """ThreadingHTTPServer that doesn't look its own address up in DNS.

    http.server's server_bind does a reverse DNS lookup of the bind address
    (socket.getfqdn) after bind() and before listen(). On a machine whose
    resolver never answers that query it blocks for minutes, so the port is
    bound but nothing is listening and a client sees a connection that is
    refused and then hangs. We only ever print our own address, so set it
    ourselves and skip the lookup.
    """

    daemon_threads = True

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = host
        self.server_port = port


def seed(hub):
    """The starting badges. Every name here is made up."""
    layla = make_print(test=False, name="Layla Example", name_local="ليلى مثال",
                       organisation="Example Trading Co", job_title="Head of Testing",
                       badge_type="Speaker", serial="K7Q2M9")
    sam = make_print(test=False, name="Sam Sample", organisation="Sample Industries",
                     job_title="Buyer", badge_type="Delegate", serial="P3X8R2",
                     reprint=True, reason="Lost badge", desk="Desk 2")
    quiet = make_print(test=False, name="Nour Placeholder", name_local="نور",
                       organisation="Example Ministry", badge_type="Press", serial="T5W1C6")
    late = make_print(test=False, name="Casey Cancelled", organisation="Example Trading Co",
                      badge_type="Delegate", serial="M4N6B8")
    # The desk asked twice: offered again under a new print id, same job key.
    twin = make_print(test=False, name="Robin Retry", organisation="Example Trading Co",
                      badge_type="Delegate", serial="R9D4V1", desk="Desk 2")
    # Stays on the waiting list after it is collected, so every client that
    # restarts, and every second client, is offered it again.
    sticky = make_print(test=False, name="Ash Repeat", organisation="Sample Industries",
                        badge_type="Delegate", serial="S2K7L4")
    for p in (layla, sam, quiet):
        hub.add(p)
    hub.add(late, withdrawn=True)
    hub.add(twin)
    hub.jobs[twin["id"]]["retry"] = True
    hub.add(sticky, sticky=True)
    return [layla, sam, late, twin, sticky], quiet, late


def main():
    ap = argparse.ArgumentParser(description="Stand-in for the FE print hub (print partner mode).")
    ap.add_argument("--port", type=int, default=8631, help="HTTP port (default 8631)")
    ap.add_argument("--mode", choices=["broadcast", "manage", "locked"], default="broadcast",
                    help="broadcast: normal. manage: every partner route answers 409. locked: 503.")
    ap.add_argument("--host", default="127.0.0.1", help="address to put in pickup URLs (default 127.0.0.1)")
    ap.add_argument("--every", type=float, default=0, help="send a sample badge every N seconds")
    a = ap.parse_args()

    def stop(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, stop)
    for name in ("SIGBREAK", "SIGTERM"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), stop)

    hub = Hub(a.mode, a.host, a.port)
    rung, quiet, late = seed(hub)
    log(f"starting on port {a.port}")  # before the bind, so a stuck bind is visible
    try:
        server = Server(("0.0.0.0", a.port), make_handler(hub))
    except OSError as e:
        sys.exit(f"Cannot use port {a.port} ({e}). Is another hub running? Try --port 8641.")
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log(f"serving http://{a.host}:{a.port}/ (mode {a.mode}). Ctrl-C stops.")
    log(f"waiting: {', '.join(p['id'] for p in rung if p is not late)}; "
        f"list only (never announced): {quiet['id']}; cancelled (410): {late['id']}")
    log("two of them try to make you print twice: Robin Retry (offered again under a new id, "
        "same jobKey) and Ash Repeat (stays on the list after collection)")

    def announce():
        time.sleep(0.5)
        for p in rung:
            hub.ring(p)

    threading.Thread(target=announce, daemon=True).start()

    try:
        next_sample = time.monotonic() + a.every if a.every > 0 else None
        while True:
            time.sleep(0.5)  # interruptible by Ctrl-C on Windows too
            if next_sample and time.monotonic() >= next_sample:
                if hub.mode == "broadcast":
                    threading.Thread(target=hub.send_sample, daemon=True).start()
                next_sample = time.monotonic() + a.every
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        log("stopped")


if __name__ == "__main__":
    main()
