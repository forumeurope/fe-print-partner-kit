#!/usr/bin/env python3
"""fake-partner-hub.py: a stand-in for the FE print hub, for developing a print partner client.

It answers the same routes, with the same JSON, as a real hub in print partner
mode, and sends the same UDP datagrams. All data is made up. Nothing is printed.

Python 3.10 or newer, standard library only. Windows, macOS and Linux.

    python fake-partner-hub.py                  start it on port 8631
    python fake-partner-hub.py --every 20       also send a sample badge every 20 s
    python fake-partner-hub.py --mode manage    answer 409, as a hub not in partner mode
    python fake-partner-hub.py --mode locked    answer 503, as a hub whose desk isn't started
    python fake-partner-hub.py --no-pdf         send no PDF, as an event that didn't ask for one

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

It also takes the two reports a partner may send back after printing:

    POST /v1/prints/<id>/printed
    POST /v1/prints/<id>/failed    {"reason": "out of ribbon"}

Both are OPTIONAL by protocol — a client that never sends them collects and
prints exactly as before — but they are the only way a desk can tell a jam from
a badge already in a delegate's hand, so send them. Only the client that
collected a badge may report on it. Each report is printed on this console and
shown on the page, so you can watch yours land.

Every badge here carries a `pdf` as well as the `image`: the same label as a
one-page PDF at 102 x 64 mm (289.13 x 181.42 pt). A real hub sends it only when
the event has "Send a PDF to the print partner" switched on, so treat it as
optional. Start with --no-pdf to see the other half: no `pdf` key at all on any
badge, the way an event with that setting off behaves. Run your client both ways
— it must print from the picture, or from the badge data, when no PDF arrives.

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
NOT_YOURS = ("This badge was collected by a different print partner client, so only that client can "
             "say what happened to it. Send the same X-Print-Collector you collected with.")
NO_REPORT_TARGET = ("There is no print with this id on this hub. Prints are kept for 10 minutes, so a "
                    "report that arrives long after the badge did has nowhere to land.")
COLLECTOR_HEADER = "X-Print-Collector"
REASON_MAX = 200    # the hub trims a partner's reason to one line of this length
COLLECTOR_MAX = 100

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


def pdf_text(s):
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def make_pdf(width_mm=102, height_mm=64, lines=("Stand-in hub", "sample badge", "102 x 64 mm")):
    """A real one-page PDF the size of the label, in points (1 mm = 72/25.4 pt).

    The hub sends the same badge as a PDF when the event has asked for one, so a
    partner who prints the ready-made vector file can develop against it here.
    This one is a frame and a few words; a real hub's is the badge itself, at the
    same page size.
    """
    w = width_mm * 72.0 / 25.4
    h = height_mm * 72.0 / 25.4
    drawn = [f"0 0 0 RG 1 w 6 6 {w - 12:.2f} {h - 12:.2f} re S", "BT /F1 14 Tf"]
    y = h - 28
    for line in lines:
        drawn.append(f"1 0 0 1 18 {y:.2f} Tm ({pdf_text(line)}) Tj")
        y -= 20
    drawn.append("ET")
    content = ("\n".join(drawn)).encode("ascii")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {w:.2f} {h:.2f}] "
         f"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>").encode("ascii"),
        b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for n, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n".encode("ascii") + body + b"\nendobj\n"
    start = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("ascii") + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode("ascii")
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{start}\n"
            "%%EOF\n").encode("ascii")
    return bytes(out)


PNG_B64 = base64.b64encode(make_png()).decode("ascii")
LOGO_B64 = base64.b64encode(make_png(120, 60, 4)).decode("ascii")
PDF_B64 = base64.b64encode(make_pdf()).decode("ascii")

# Whether badges carry a `pdf` at all. --no-pdf turns it off, which is what an
# event with "Send a PDF to the print partner" switched off looks like on the wire.
SEND_PDF = True

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
        # OPTIONAL on a real hub: the same badge as a PDF at the label's exact mm
        # size, sent only when the event asked for it. This stand-in sends one
        # unless you start it with --no-pdf, so a partner who prints the PDF can
        # develop against it; a partner who uses the PNG, or their own design,
        # ignores it. With --no-pdf the key is absent, not null.
        **({"pdf": {"contentType": "application/pdf", "widthMm": 102, "heightMm": 64,
                    "base64": PDF_B64}} if SEND_PDF else {}),
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
        self.last_report = None   # what the last partner report said, for the page
        self.reports = []         # every report this hub was told, newest last
        self.lock = threading.Lock()

    def add(self, p, withdrawn=False, sticky=False):
        """sticky: stays on the waiting list after it is collected, the way a
        client that restarts sees a badge offered to it a second time. A client
        that keeps a record of what it printed saves it once anyway."""
        with self.lock:
            self.jobs[p["id"]] = {"print": p, "created": time.monotonic(), "picked": None,
                                  "withdrawn": withdrawn, "sticky": sticky, "by": None,
                                  "report": None, "event": threading.Event()}

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

    @staticmethod
    def clean_reason(reason):
        """The partner's words as the hub keeps them: one line, no control characters,
        no double spaces, 200 characters at most. They go on a desk screen."""
        if not isinstance(reason, str):
            return None
        line = " ".join("".join(" " if ch < " " else ch for ch in reason).split())
        return line[:REASON_MAX] or None

    def report(self, print_id, outcome, collector=None, reason=None):
        """What a partner says it did with a badge it collected.

        OPTIONAL by protocol: a partner that never calls this works exactly as
        one that does. Answered like a collect, so a client that handles the
        collect's codes needs nothing new:

          * no such print          -> "unknown" (404)
          * nobody holds it, or somebody else does -> "notyours" (409)
          * the desk already gave up on it -> "cancelled", 200, applied false
          * this job already carries a report -> "already reported", 200,
            applied false; the FIRST report stands, so a client retrying a lost
            reply cannot flip an outcome
          * otherwise -> "recorded", 200, applied true
        """
        with self.lock:
            self.sweep()
            j = self.jobs.get(print_id)
            if j is None:
                return "unknown", None
            if j["withdrawn"]:
                # Too late to change anything, but telling a partner off for being
                # honest is a good way to stop them reporting. Kept as a record.
                if j["report"] is None:
                    self._store(j, outcome, collector, reason)
                return "cancelled", j
            if not j["picked"] or not collector or j["by"] != collector:
                return "notyours", j
            if j["report"] is not None:
                return "already reported", j
            self._store(j, outcome, collector, reason)
            return "recorded", j

    def _store(self, j, outcome, collector, reason):
        # A reason belongs to a failure: "printed" carries none, as the hub does.
        report = {"outcome": outcome, "at": utc_now(), "by": collector,
                  "reason": self.clean_reason(reason) if outcome == "failed" else None,
                  "id": j["print"]["id"], "desk": j["print"].get("desk")}
        j["report"] = report
        self.reports.append(report)
        self.last_report = report

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
<p id="report"></p>
<script>
async function show(){const m=await (await fetch('/v1/bench/print-mode')).json();
document.getElementById('mode').textContent=m.mode;
document.getElementById('stat').textContent=(m.lastPickupAt?'Last collected '+m.lastPickupAt:'Nothing collected yet')+'. Waiting: '+m.waitingForPickup;
const r=m.lastReport;document.getElementById('report').textContent=r?('Last report: '+r.outcome+' for '+r.id+' at '+r.at+(r.reason?' - '+r.reason:'')):'No partner report yet (reports are optional).';}
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
                    "lastPickupAt": hub.last_pickup, "waitingForPickup": len(hub.waiting()),
                    "lastReport": hub.last_report}

        def report_totals(self):
            """What partners have told this hub, the way a real hub's /v1/status says it."""
            printed = [r for r in hub.reports if r["outcome"] == "printed"]
            failed = [r for r in hub.reports if r["outcome"] == "failed"]
            last = failed[-1] if failed else None
            return {
                "partnerPrinted": len(printed),
                "partnerFailed": len(failed),
                "lastPrintedAt": printed[-1]["at"] if printed else None,
                "lastFailureAt": last["at"] if last else None,
                "partnerFailure": None if last is None else {
                    "at": last["at"], "desk": last["desk"], "reason": last["reason"],
                    "message": (f"{last['desk']}: the print partner reported a failure"
                                + (f" — {last['reason']}" if last["reason"] else ".")),
                },
            }

        def report_body(self):
            """The report's body, when there is one. No body, an empty body or JSON we
            cannot read is a report with nothing said — never an error: the outcome is
            in the path."""
            try:
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                body = json.loads(raw or b"{}")
                return body if isinstance(body, dict) else {}
            except (ValueError, OSError):
                return {}

        def do_report(self, path):
            """POST /v1/prints/<id>/printed and /failed."""
            if not self.partner_ready():
                return
            head, outcome = path.rsplit("/", 1)
            try:
                print_id = str(uuid.UUID(head.rsplit("/", 1)[-1]))
            except ValueError:
                return self.send(404, b"", "text/plain")
            body = self.report_body()
            collector = (self.headers.get(COLLECTOR_HEADER) or "").strip()
            if not collector:
                collector = str(body.get("collector") or "").strip()[:COLLECTOR_MAX]
            state, j = hub.report(print_id, outcome, collector or None, body.get("reason"))
            log(f"report {outcome} for {print_id} {state} "
                f"(from {collector or 'a client with no id'}"
                + (f", reason: {hub.clean_reason(body.get('reason'))}"
                   if outcome == "failed" and body.get("reason") else "") + ")")
            if state == "unknown":
                return self.problem(404, "No such print", NO_REPORT_TARGET)
            if state == "notyours":
                return self.problem(409, "Not your badge", NOT_YOURS)
            got = (j or {}).get("report")
            self.send(200, {
                "id": print_id,
                "outcome": outcome,
                "recorded": True,
                "applied": state == "recorded",
                "state": state,
                "reportedOutcome": got["outcome"] if got else None,
            })

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/":
                self.send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/v1/bench/print-mode":
                self.send(200, self.mode_view())
            elif path == "/v1/status":
                v = self.mode_view()
                self.send(200, {"hubName": HUB_NAME, "printMode": v["mode"],
                                "lastPickupAt": v["lastPickupAt"], "waitingForPickup": v["waitingForPickup"],
                                **self.report_totals()})
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
            path = self.path.split("?", 1)[0]
            if path.startswith("/v1/prints/") and path.rsplit("/", 1)[-1] in ("printed", "failed"):
                return self.do_report(path)
            if path != "/v1/bench/sample-print":
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
    ap.add_argument("--no-pdf", action="store_true",
                    help="leave the pdf off every badge, as an event that hasn't asked the hub "
                         "for one does. Without it every badge carries a one-page PDF at the "
                         "label's size (102 x 64 mm = 289.13 x 181.42 pt).")
    a = ap.parse_args()

    global SEND_PDF
    SEND_PDF = not a.no_pdf

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
    log("badges carry a pdf (102 x 64 mm)" if SEND_PDF else
        "--no-pdf: badges carry no pdf, as an event that hasn't asked for one")

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
