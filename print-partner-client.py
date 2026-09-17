#!/usr/bin/env python3
"""Example print partner client for the FE print hub.

Listens for the hub's "a badge is ready" datagram on UDP port 8632, also checks
the hub's waiting list every 5 seconds, collects each badge and saves it as
<id>.png, <id>.json and — when the badge carries one — <id>.pdf in a folder.
Put your own printing in print_badge(); it shows the three ways to print.

After printing it tells the hub what happened: POST /v1/prints/<id>/printed, or
/failed with a reason. That is optional by protocol, and a report that does not
arrive is dropped rather than retried, but it is the only way the desk can tell
a jam from a badge already in a delegate's hand.

Python 3.10 or newer, standard library only. Windows, macOS and Linux.

    python print-partner-client.py --hub 127.0.0.1           (the stand-in hub)
    python print-partner-client.py --hub 192.168.8.20 --out C:\\badges
    python print-partner-client.py --hub 127.0.0.1 --forget  (clear the record)

A cancelled badge (HTTP 410) must never be printed. Ctrl-C stops.

NEVER PRINTING A BADGE TWICE
----------------------------
This is the part to copy into your own system. A delegate handed two badges is
a real complaint at the desk, and the hub announces each badge three times, on
every network, so repeats are normal, not a fault.

Three things keep it to one badge:

  1. An id seen twice is one badge. Each announcement carries a print id; the
     three rings all carry the same one, and the waiting list repeats it every
     5 seconds. Held in memory (self.inflight) while a badge is being fetched.
  2. A record on disk (printed.json, beside the badge folder) of every print id
     and job key this client has finished with. Checked BEFORE collecting and
     again BEFORE saving or printing, so a restart, a crash or a second run
     never prints a badge again. --forget clears it, for testing only.
  3. One collector id, kept in that record and sent as X-Print-Collector. The
     hub hands each badge to ONE client: a second client asking gets 409, and
     this client can re-ask for its own badge safely after a dropped reply.

The job key is the DESK's id for the badge. The hub may offer one badge again
under a new print id (the desk gave up waiting and asked again); the job key
stays the same, so keying on it stops that becoming a second badge. A reprint
or a second day's badge arrives under a NEW job key and IS printed: it is a new
badge, not a repeat.

See print-partner-spec.md, "Never print a badge twice".
"""

import sys

if sys.version_info < (3, 10):
    sys.exit("This needs Python 3.10 or newer. You have "
             f"{sys.version.split()[0]}. Get it from https://www.python.org/downloads/")

import argparse
import base64
import json
import os
import signal
import socket
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

DOORBELL_PORT = 8632
HUB_PORT = 8631
POLL_EVERY = 5  # seconds
COLLECTOR_HEADER = "X-Print-Collector"
# How many finished badges the record keeps. A print lives on the hub for ten
# minutes at most and ids are never reused, so the oldest can be dropped.
RECORD_KEEP = 10000

# Hub messages may carry Arabic names. Never crash on a console that can't show them.
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(errors="backslashreplace")
    except (AttributeError, ValueError):
        pass


def say(msg):
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


def print_badge(job, png_path, pdf_path=None):
    """YOUR PRINTING GOES HERE.

    job is the full badge (a dict): the badge fields, the event, the design, the
    size, a finished picture, and a finished PDF when the event asked for one.
    png_path is the saved picture; pdf_path is the saved PDF, or None.

    Return normally when the badge came out of the printer, and raise when it did
    not. The caller reports that back to the hub (printed / failed) so the desk
    can tell a jam from a badge already in a delegate's hand. Reporting is
    optional by protocol: if you take this out, everything else still works.

    THREE WAYS TO PRINT, most likely first.

    (a) YOUR OWN DESIGN from our data. What most partners do: you have a badge
        design and a printer that knows it, and all you want from us are the
        words. Everything you need is in job["badge"] — name, nameLocal (the
        local-script name, often Arabic), organisation, jobTitle, type, qr,
        serial — plus job["event"]["name"]. Nothing else here is needed.

            b, event = job["badge"], job.get("event") or {}
            your_printer.print_label(
                name=b["name"], name_local=b.get("nameLocal"),
                organisation=b.get("organisation"), job_title=b.get("jobTitle"),
                badge_type=b.get("type"), qr=b["qr"], event=event.get("name"))

    (b) OUR PICTURE, ready made. job["image"] is the whole badge as a PNG at
        job["image"]["dpi"] dots per inch (203 on a label printer). Send it at
        that dpi with NO scaling and no "fit to page": scaling is what makes a
        QR code unreadable and a name soft.

            subprocess.run(["lp", "-d", "YourPrinter", "-o", "media=Custom.102x64mm",
                            "-o", "scaling=100", str(png_path)], check=True)

    (c) OUR PDF, ready made, when it is there. job.get("pdf") is the same badge
        as a one-page PDF at exactly widthMm x heightMm. Print it at its own page
        size — again no scaling, no margins. It is OPTIONAL: absent unless the
        event turned it on, so always check before using it.

            if pdf_path:
                subprocess.run(["lp", "-d", "YourPrinter", "-o", "media=Custom.102x64mm",
                                "-o", "fit-to-page=false", str(pdf_path)], check=True)

        Most partners will send the saved PDF through their own print stack instead.
        If you want to hand it straight to a printer, these two lines are a starting
        point — we have not tested either on your kit, so treat them as examples:

            macOS/Linux: subprocess.run(["lpr", "-P", "YourPrinter",
                                         "-o", "media=Custom.102x64mm", str(pdf_path)], check=True)
            Windows:     subprocess.run(["SumatraPDF.exe", "-print-to", "YourPrinter",
                                         "-print-settings", "noscale", str(pdf_path)], check=True)
                         (or PowerShell: Start-Process -FilePath <pdf> -Verb Print, which
                          uses whatever the machine's default PDF reader does)

    What this example client actually does is neither: it saves the files and
    says what it would have printed.
    """
    b = job["badge"]
    size = job["size"]
    test = " [TEST]" if job.get("test") else ""
    extra = f", pdf {pdf_path.name}" if pdf_path else ""
    say(f"  -> would print {b.get('name')!r} ({size['widthMm']} x {size['heightMm']} mm){test}{extra}")


def problem_detail(err):
    """The hub's plain-English reason from an error response."""
    try:
        return json.loads(err.read().decode("utf-8")).get("detail") or ""
    except (ValueError, OSError, AttributeError):
        return ""


def one_line(e):
    """An exception as one short line, for the hub to show the desk."""
    text = " ".join(str(e).split()) or e.__class__.__name__
    return text[:200]


def write_atomic(path, data):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


class Record:
    """What this client has already finished with, kept on disk so a restart
    cannot print a badge a second time.

    Two keys per badge: the print id (this offer) and the job key (the desk's
    badge, the same across a desk retry under a new print id). Either one
    already in here means DO NOT PRINT. Also holds this client's own collector
    id, so the hub knows the same client across restarts.

    Written whole, atomically, after every badge. Losing it is not a disaster
    (the hub only keeps a print for ten minutes) but never printing twice while
    it is there is the point, so it is written BEFORE anything is printed.
    """

    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        self.lock = threading.Lock()
        self.ids = {}       # print id -> what happened
        self.keys = {}      # desk job key -> print id we handled it under
        self.collector = ""
        self._load()

    def _load(self):
        try:
            data = json.loads(self.path.read_bytes().decode("utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        done = data.get("done")
        self.ids = dict(done) if isinstance(done, dict) else {}
        self.keys = {v.get("jobKey"): k for k, v in self.ids.items()
                     if isinstance(v, dict) and v.get("jobKey")}
        self.collector = str(data.get("collector") or "") or f"fe-partner-{uuid.uuid4()}"
        if not data.get("collector"):
            self._save()

    def _save(self):
        if len(self.ids) > RECORD_KEEP:  # oldest first: dicts keep insertion order
            for old in list(self.ids)[:len(self.ids) - RECORD_KEEP]:
                self.keys.pop(self.ids.pop(old).get("jobKey"), None)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            write_atomic(self.path, json.dumps(
                {"version": 1, "collector": self.collector, "done": self.ids},
                ensure_ascii=False, indent=2).encode("utf-8"))
        except OSError as e:
            # Keep going in memory. Say it once: a client that cannot write its
            # record CAN print a badge again after a restart.
            if not getattr(self, "_warned", False):
                say(f"WARNING: cannot write {self.path} ({e}). A restart could print a badge again.")
                self._warned = True

    def handled(self, print_id, job_key=None):
        """Has this badge been dealt with already — under this id, or as this desk badge?"""
        with self.lock:
            return print_id in self.ids or (bool(job_key) and job_key in self.keys)

    def done(self, print_id, job_key=None, what="printed"):
        """Remember this badge before it is printed, never after."""
        with self.lock:
            self.ids[print_id] = {"jobKey": job_key, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                  "what": what}
            if job_key:
                self.keys[job_key] = print_id
            self._save()

    def forget_all(self):
        with self.lock:
            self.ids, self.keys = {}, {}
            self._save()


class Client:
    def __init__(self, hub, port, out, record):
        self.base = f"http://{hub}:{port}"
        self.port = port
        self.out = Path(out).expanduser().resolve()
        self.record = record
        self.inflight = set()   # print ids being fetched right now (repeat announcements)
        self.lock = threading.Lock()
        self.out.mkdir(parents=True, exist_ok=True)

    def get(self, url):
        request = urllib.request.Request(url, headers={COLLECTOR_HEADER: self.record.collector})
        with urllib.request.urlopen(request, timeout=5) as r:
            return json.load(r)

    def report(self, print_id, outcome, reason=None):
        """Tell the hub what happened to a badge we collected: printed, or failed.

        OPTIONAL by protocol — take it out and everything else works exactly as
        before — but without it the desk cannot tell a jam from a badge already
        in a delegate's hand, so send it.

        It must never be able to break printing. A report that does not arrive is
        said once and dropped: never retried in a loop, never a reason to collect
        or print the badge again. The badge is already printed; the hub only
        misses the news. Only the client that collected the badge may report on
        it, hence the same X-Print-Collector id we collected with.
        """
        url = f"{self.base}/v1/prints/{print_id}/{outcome}"
        body = json.dumps({"reason": reason} if reason else {}).encode("utf-8")
        request = urllib.request.Request(
            url, data=body, method="POST",
            headers={COLLECTOR_HEADER: self.record.collector, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=5) as r:
                answer = json.load(r)
            state = answer.get("state") if isinstance(answer, dict) else None
            say(f"  reported {outcome} for {print_id}: {state or 'accepted'}")
        except urllib.error.HTTPError as e:
            # 404 (the hub no longer holds it), 409 (somebody else collected it),
            # 410 or anything else: nothing to do about it here.
            say(f"  could not report {outcome} for {print_id}: HTTP {e.code} {problem_detail(e)}")
        except (OSError, ValueError) as e:
            say(f"  could not report {outcome} for {print_id}: {e}")

    def release(self, print_id):
        with self.lock:
            self.inflight.discard(print_id)

    def pick_up(self, print_id, url, job_key=None):
        # DEDUPE, BEFORE COLLECTING. Three checks, cheapest first: this badge is
        # already being fetched (a repeat announcement), or it was finished with
        # in an earlier run (the record on disk), or its desk badge was.
        if self.record.handled(print_id, job_key):
            return
        with self.lock:
            if print_id in self.inflight:
                return
            self.inflight.add(print_id)
        try:
            job = self.get(url)
        except urllib.error.HTTPError as e:
            if e.code == 410:
                # Cancelled: the desk stopped waiting. Never print it, never ask again.
                say(f"cancelled {print_id}: not collected in time, NOT printed")
                self.record.done(print_id, job_key, "cancelled")
                return
            if e.code == 409:
                # Another collector on this network has it, and is printing it.
                # Never print it here: that is exactly the duplicate badge.
                say(f"{print_id} was collected by another client: NOT printed here")
                self.record.done(print_id, job_key, "collected-elsewhere")
                return
            if e.code == 404:
                # Not on our hub (another hub on the network) or already deleted. Drop it.
                self.release(print_id)
                return
            say(f"collect {print_id} failed: HTTP {e.code} {problem_detail(e)}")
            self.release(print_id)
            return
        except (OSError, ValueError) as e:
            say(f"collect {print_id} failed: {e}")
            self.release(print_id)
            return

        # DEDUPE, AGAIN, BEFORE SAVING OR PRINTING. The badge now names its own
        # desk job key; a retry the desk made under a new print id is caught here.
        key = job.get("jobKey") or job_key
        if self.record.handled(print_id, key):
            say(f"{print_id} is a repeat of a badge already printed: NOT printed again")
            return

        # Written down BEFORE a pixel is printed. If this client dies between
        # here and the printer the badge is not printed twice — ask the desk to
        # print it again, which is a new job key and a new badge.
        self.record.done(print_id, key, "printed")

        # PNG (and the PDF when there is one) first, JSON last: a folder watcher
        # can treat the .json as "complete".
        png_path = self.out / f"{print_id}.png"
        write_atomic(png_path, base64.b64decode(job["image"]["base64"]))
        pdf_path = None
        pdf = job.get("pdf")
        # Optional: only there when the event asked the hub for a PDF as well.
        if isinstance(pdf, dict) and pdf.get("base64"):
            pdf_path = self.out / f"{print_id}.pdf"
            write_atomic(pdf_path, base64.b64decode(pdf["base64"]))
        write_atomic(self.out / f"{print_id}.json",
                     json.dumps(job, ensure_ascii=False, indent=2).encode("utf-8"))
        say(f"collected {print_id} from {job.get('desk')} -> {png_path}")
        try:
            print_badge(job, png_path, pdf_path)   # called at most once per print id, ever
        except Exception as e:  # your printing failing must not stop collection
            say(f"  print_badge failed: {e!r}")
            self.report(print_id, "failed", one_line(e))
        else:
            self.report(print_id, "printed")

    def open_doorbell(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Lets another program on this computer listen too. SO_REUSEPORT is macOS/Linux only.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass
        sock.bind(("", DOORBELL_PORT))
        return sock

    def listen(self):
        """The doorbell. UDP can be dropped, so poll_once() is the safety net."""
        try:
            sock = self.open_doorbell()
        except OSError as e:
            say(f"cannot listen on UDP {DOORBELL_PORT} ({e}); checking the waiting list only")
            return
        say(f"listening for badges on UDP {DOORBELL_PORT}")
        while True:
            try:
                data, _ = sock.recvfrom(4096)
                bell = json.loads(data.decode("utf-8"))
                if not (isinstance(bell, dict) and bell.get("fehub") == 1 and bell.get("type") == "print"):
                    continue
                print_id = str(uuid.UUID(str(bell["id"])))  # also keeps file names safe
            except (ValueError, KeyError, OSError):
                continue
            # The hub rings three times, on every network, so most datagrams
            # here are repeats. pick_up() drops them; nothing is fetched twice.
            # Collect from OUR hub, not from whoever sent this: a datagram from
            # another hub on the network is then a 404 and is ignored.
            url = f"{self.base}/v1/prints/{print_id}"
            threading.Thread(target=self.pick_up, args=(print_id, url), daemon=True).start()

    def poll_once(self):
        """The waiting list: catches anything a datagram missed. Returns the next delay."""
        try:
            for w in self.get(f"{self.base}/v1/prints")["waiting"]:
                print_id = str(uuid.UUID(str(w["id"])))
                # The list names the desk badge too, so a badge already printed
                # is skipped here without collecting it at all.
                self.pick_up(print_id, f"{self.base}/v1/prints/{print_id}", w.get("jobKey"))
            if getattr(self, "last_problem", None):
                say("hub ready: collecting badges")
            self.last_problem = None
            return POLL_EVERY
        except urllib.error.HTTPError as e:
            # 409: not in print partner mode. 503: the desk hasn't been started.
            reason = problem_detail(e) or {
                409: "The hub is not in print partner mode. Ask the FE team to switch it on.",
                503: "The hub's desk has not been started yet.",
            }.get(e.code, "")
            msg = f"hub not ready (HTTP {e.code}): {reason}"
            if msg != getattr(self, "last_problem", None):
                say(f"{msg} Retrying every {POLL_EVERY}s.")
                self.last_problem = msg
            return POLL_EVERY
        except (OSError, ValueError, KeyError) as e:
            say(f"cannot reach the hub at {self.base} ({e})")
            self.last_problem = None
            return None


def stop(*_):
    raise KeyboardInterrupt


def main():
    p = argparse.ArgumentParser(description="FE print hub: example print partner client")
    p.add_argument("--hub", required=True, help="the hub's address (127.0.0.1 for the stand-in hub)")
    p.add_argument("--port", type=int, default=HUB_PORT, help=f"the hub's port (default {HUB_PORT})")
    p.add_argument("--out", default="badges", help="folder to save badges in (default ./badges)")
    p.add_argument("--record", default=None,
                   help="the list of badges already printed (default <out>.printed.json)")
    p.add_argument("--forget", action="store_true",
                   help="empty that list first, so badges already printed are printed again (testing only)")
    p.add_argument("--run-for", type=float, default=0, help="stop after this many seconds (for tests)")
    a = p.parse_args()

    # Ctrl-C everywhere; Ctrl-Break on Windows; a plain kill elsewhere.
    signal.signal(signal.SIGINT, stop)
    for name in ("SIGBREAK", "SIGTERM"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), stop)

    out = Path(a.out).expanduser().resolve()
    record = Record(a.record or out.with_name(out.name + ".printed.json"))
    if a.forget:
        record.forget_all()
        say(f"forgot every badge in {record.path}: they can be printed again")

    c = Client(a.hub, a.port, out, record)
    say(f"hub {c.base}, saving to {c.out}. Ctrl-C stops.")
    say(f"already printed: {len(record.ids)} badge(s) remembered in {record.path} "
        f"(collector {record.collector})")
    threading.Thread(target=c.listen, daemon=True).start()
    end = time.monotonic() + a.run_for if a.run_for > 0 else None
    backoff = POLL_EVERY
    try:
        while end is None or time.monotonic() < end:
            if c.poll_once():
                delay, backoff = POLL_EVERY, POLL_EVERY
            else:
                delay, backoff = backoff, min(backoff * 2, 60)
                say(f"trying again in {delay}s")
            wait = delay if end is None else max(0.0, min(delay, end - time.monotonic()))
            time.sleep(wait)  # interruptible by Ctrl-C on Windows too
    except KeyboardInterrupt:
        pass
    say("stopped")


if __name__ == "__main__":
    main()
