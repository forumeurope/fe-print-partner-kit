# FE print partner kit

Everything a print supplier needs to print the name badges at an FE event:
the interface, an example client, a stand-in hub to build against, and real
samples.

**The model in one line: we announce every badge that needs printing, and
your system does the rest.**

| File | What it is |
|------|------------|
| [`print-partner-spec.md`](print-partner-spec.md) | The interface. Every field, every status code. The reference. |
| [`fe-print-partner-spec.pdf`](fe-print-partner-spec.pdf) | The same document as a PDF, to read away from the screen. |
| [`print-partner-client.py`](print-partner-client.py) | An example client: listens, collects, saves each badge. Your printing goes in one marked function. |
| [`fake-partner-hub.py`](fake-partner-hub.py) | A stand-in hub on your own computer, so you can build and test without us. |
| `start-*.bat`, `start-*.command` | Double-click launchers for Windows and macOS. |
| [`samples/`](samples) | A real announcement, a test badge and its picture. |
| [`CHANGELOG.md`](CHANGELOG.md) | What changed in each spec version. |

Python 3.10 or newer, standard library only. Nothing else to install.

## Getting started

Take the whole kit as one file from the
[latest release](https://github.com/forumeurope/fe-print-partner-kit/releases/latest) —
`fe-print-partner-kit.zip`, about 450 KB, with the spec PDF beside it. Unzip it and you have
everything.

Or clone it, which makes updates a `git pull`:

```
git clone https://github.com/forumeurope/fe-print-partner-kit.git
cd fe-print-partner-kit
python3 fake-partner-hub.py            # a stand-in hub, in one window
python3 print-partner-client.py --hub 127.0.0.1   # the client, in another
```

Badges land in `badges/` as `<id>.png` and `<id>.json`. Then put your own
printing in `print_badge()`.

## Keeping up to date

`git pull` for the latest, or watch the
[releases](https://github.com/forumeurope/fe-print-partner-kit/releases) - each one is a spec version,
and each carries the whole kit as a zip. This copy is
**spec version 1**.

## Questions

Open an [issue](https://github.com/forumeurope/fe-print-partner-kit/issues) - we would rather answer
one here than by email, so the answer stays with the kit.

---

The rest of this page is the kit's own `README.txt`, the short way in.

```text
FE PRINT PARTNER KIT
====================

This kit is for a print supplier printing the name badges at an FE event.

At the event our print hub broadcasts a small UDP message on port 8632 each
time a check-in desk asks for a badge. Your computer fetches that badge over
HTTP from the hub on port 8631 and gets the delegate's data as JSON, together
with a rendered PNG of the badge and, if the event has asked for it, a PDF.
There is no login and no key: the event network is the boundary. You print the
badge on your own kit.

WHAT THIS IS FOR
----------------
Most partners use this interface to print THEIR OWN badge design and take only
our data to fill it in: the delegate's name, their name in their own script
where we have one, their organisation, job title and delegate type, the exact
QR text and the badge serial, plus the event name. Your layout, stock, fonts,
colours, drivers and colour management stay yours; none of that is ours to
specify.

The rendered PNG we send is there if you would rather not lay anything out —
it is exactly what our own thermal printers produce — and the optional PDF is
the same badge as vector at the stock's exact millimetre size. Use whichever
suits you.

Two things make the badge work on the day, whatever you print on:
  - the QR text encoded exactly as sent, and scannable - our door scanners
    read it, and a code that does not scan holds a delegate up;
  - the name legible at arm's length, in the script we sent it in.

There are also two routes for telling us how a badge went, "printed" and
"failed". They are available, not required - see TELLING US HOW IT WENT.

  WHAT WE GIVE YOU                 | WHAT YOU BUILD
  ---------------------------------|-----------------------------------
  The event network and the hub    | Your own printing, from the badge
  The UDP message on 8632          |   data or from our picture
  The badge over HTTP on 8631:     | Your queue, retries and operators
    the data, the QR text, our     | The printer, the stock and the
    design, a PNG, sometimes a PDF |   settings

print-partner-spec.md is the full interface: the datagram, the pickup, the
waiting list, every field, every status code and the reports. That file is the
reference; this one only gets you started.


TERMS
-----
  datagram       The UDP message on port 8632 announcing that a badge is
                 ready. Older documents called it the announcement or the
                 doorbell.
  badge          One delegate's badge: the JSON, and the thing you print.
  job id         The hub's id for one offer of a badge ("id").
  job key        The desk's id for the badge itself ("jobKey"), stable
                 across a retry.
  collector      Your software, identified by X-Print-Collector.
  collect        GET a badge. The first successful GET takes it.
  waiting list   The badges nobody has collected yet.
  cancelled      A badge the hub took back. It answers 410. Never print it.


REQUIREMENTS
------------
Python 3.10 or later, and nothing else.

  macOS    Install from https://www.python.org/downloads/ ,
           or with Homebrew: brew install python
  Windows  Install from https://www.python.org/downloads/ and tick
           "Add python.exe to PATH" on the first screen. The bundled "py"
           launcher works too.

Check it: open Terminal (macOS) or Command Prompt (Windows) and run
  python3 --version      (macOS)
  py -3 --version        (Windows)


QUICK START A - one computer, no event
--------------------------------------
The kit contains a stand-in hub that serves invented badges, so you can build
against the whole path without our hardware.

  macOS
    1. Double-click start-fake-hub-mac.command. Leave the window open.
    2. Double-click start-client-mac.command. Press Enter to accept
       127.0.0.1 as the hub address.

  Windows
    1. Double-click start-fake-hub-windows.bat. Leave the window open.
    2. Double-click start-client-windows.bat. Press Enter to accept
       127.0.0.1 as the hub address.

The stand-in hub sends a PDF on every badge, so you can try that route too:
print a saved <id>.pdf on the stock you mean to use. Start it with --no-pdf and
it behaves like an event that has the setting switched off, which is worth
checking your code takes in its stride.

Within a few seconds the client saves each badge into the "badges" folder
beside these files: <id>.png (the rendered picture), <id>.json (everything,
including the data you would fill your own design with) and <id>.pdf when the
badge carries one. One badge arrives only through the client's regular poll of
the waiting list, so it can take about 10 seconds. One badge is cancelled and
the client skips it, which is correct. Two more are deliberate attempts to make
you print the same badge twice; the client does not, and neither must your
system. Read NEVER PRINT A BADGE TWICE below.

If macOS refuses to open the .command file, right-click it and choose Open, or
run it from Terminal:  bash start-client-mac.command

Stop either window with Ctrl-C, or close it.


QUICK START B - at the event, against the real hub
--------------------------------------------------
  1. Put a network cable into our router; we give you the port. Use the
     cable. Wi-Fi drops broadcasts and degrades in a crowd, so we give you
     Wi-Fi details only as a fallback.
  2. We give you the hub's address on the day (for example 192.168.8.20).
  3. Start the client and give it that address:
       macOS    double-click start-client-mac.command
       Windows  double-click start-client-windows.bat
     or directly:
       bash start-client-mac.command 192.168.8.20
       start-client-windows.bat 192.168.8.20
  4. Ask us to send a test badge. A test badge has "test": true.

There is no joint test before the event: setup day at the venue is the first
time your software meets our hub. Test against the stand-in hub until then -
it sends the same datagrams and the same badge payloads on the same ports, so
a system that works against it works against ours.

Have ready on setup day: the machine that will run all event, with your
software installed and already working against the stand-in hub; your printers,
stock and consumables; a network cable for our router; and somebody who can
change your settings on the spot.

Do not run the stand-in hub at the event.


WHAT EACH FILE IS
-----------------
  README.txt                    This file.
  print-partner-spec.md         The full interface: the datagram, the pickup,
                                the waiting list, the fields, the reports and
                                the status codes.
  print-partner-client.py       A working reference client. Your printing goes
                                in the function print_badge(); everything else
                                can stay as it is.
  fake-partner-hub.py           The stand-in hub, serving invented badges. For
                                development only.
  start-client-mac.command      Starts the client (macOS).
  start-fake-hub-mac.command    Starts the stand-in hub (macOS).
  start-client-windows.bat      Starts the client (Windows).
  start-fake-hub-windows.bat    Starts the stand-in hub (Windows).
  samples/                      One real datagram, one real badge, its picture
                                and the same badge as a PDF (pickup.pdf) -
                                print that on your stock before you write
                                anything.
  badges.printed.json           The client's record of what it has printed.
                                Do not delete it while the event is running.

The launchers take optional arguments:
  start-client-*    [hub address] [hub port]    (defaults 127.0.0.1, 8631)
  start-fake-hub-*  [port]                      (default 8631)
  Windows only: add /nopause to close the window without a key press.

To run the client directly:
  python3 print-partner-client.py --hub <address> [--port 8631] [--out badges]
                                 [--record FILE] [--forget]


TELLING US HOW IT WENT
----------------------
If you want to, you can tell the hub what happened to a badge:

  POST http://<hub>:8631/v1/prints/<id>/printed
  POST http://<hub>:8631/v1/prints/<id>/failed   {"reason": "out of ribbon"}

with your X-Print-Collector header on the request. The reference client does
this already: "printed" when its print hook returns, "failed" with the error
text when it raises.

What we do with them: a "failed" report reaches the desk and is shown there
like any other print failure, with your reason in the sentence ("Desk 1: the
print partner reported a failure - out of ribbon"), and the operator is offered
a reprint, which reaches you as a new badge with a new job key. Without it, a
jam and a successful print look identical from the desk: the iPad says printed,
the steward turns round, and there is nothing to hand over. A "printed" report
closes the badge quietly.

Nothing depends on them. A client that never sends them behaves exactly the
same, and no badge waits for one. Report once per badge; a repeat is accepted
and changes nothing. If a report call fails, note it and carry on - there is
nothing to retry in a loop, and it should never hold up the next badge.
Section 8 of the spec has the rules and the status codes.


NEVER PRINT A BADGE TWICE
-------------------------
A delegate holding two badges is the complaint we hear at the desk. The hub
announces each badge three times on every network, and the waiting list repeats
it every 5 seconds, so you will hear about one badge five or six times on an
ordinary morning. That is normal, not a fault.

Each badge carries a job id ("id") and the desk's job key ("jobKey"). The hub
serves a badge to ONE collector and answers 409 to a second. The reference
client records every job id and job key it has printed in badges.printed.json,
checks that file before it collects and again before it prints, and sends its
own X-Print-Collector on every request, so a restart, a repeat datagram or a
second client never reprints a badge. Copy that behaviour.

Run ONE collector. A spare machine, or yesterday's process nobody stopped, is
the usual explanation for everything printing twice.

A reprint, or a badge for a new day, arrives with a NEW job key. It is a new
badge and you must print it.

--forget empties the record so you can reprint a test badge. Never use it at an
event.

Section 10 of print-partner-spec.md has the detail.


FIREWALL
--------
The client must receive UDP on port 8632 and connect out to TCP 8631. Your
firewall has to allow both.

  macOS    If macOS asks whether Python may accept incoming network
           connections, choose Allow. If you missed it: System Settings >
           Network > Firewall > Options, and set Python to "Allow incoming
           connections".
  Windows  When Defender asks about Python, tick "Private networks" and click
           Allow. If you missed it: Control Panel > Windows Defender Firewall >
           Allow an app through Windows Defender Firewall, and tick Private for
           Python. Set the event network as Private as well.


RULES THAT MATTER
-----------------
  - A badge that answers 410 is cancelled. Do not print it: the desk stopped
    waiting and may already have printed a replacement.
  - The hub can announce the same badge more than once. Print it once.
  - Print the QR text exactly as sent.
  - A badge holds personal data. Delete the saved files after the event.


TROUBLESHOOTING
---------------
No badges arrive:
  - Is your cable in our router, and is the link light on?
  - Is the firewall blocking Python? See FIREWALL above.
  - Start the client with the hub's address (--hub <address>, or type it when
    the client asks). It then also polls the hub's waiting list every 5
    seconds, which works even when the network swallows the datagrams.
  - "cannot reach the hub": check the address with us, and check you can open
    http://<address>:8631/v1/prints in a browser.
  - "hub not ready (HTTP 409)": the hub is not in print partner mode yet. Ask
    us to switch it.
  - "hub not ready (HTTP 503)": nobody has started the desk. Wait, or ask us.

"Address already in use" with the stand-in hub:
  A second copy is already running. Close it, or start on another port:
  start-fake-hub-mac.command 8641 and then start-client-mac.command
  127.0.0.1 8641 (the same on Windows).

Only one program per machine can listen for the datagrams at a time. If
something else holds the port, the client still finds badges through the
waiting list.
```
