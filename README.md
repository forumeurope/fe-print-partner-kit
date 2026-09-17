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

This kit is for a print supplier. The system of that supplier prints the name
badges at an FE event.

The model in one sentence:
  We announce what we must print. You collect it and you print it.

At the event, our print hub sends a small UDP message on port 8632 each time
that a check-in desk asks for a badge. This message is the announcement. Your
computer collects the badge over HTTP from the hub on port 8631. There is no
login and no key. You print the badge in the way that you want.

  WHAT WE GIVE YOU                 | WHAT YOU BUILD
  ---------------------------------|-----------------------------------
  The event network and the hub    | Your own printing, from the badge
  The announcement on UDP 8632     |   picture or the badge data
  The badge over HTTP on 8631:     | Your queue, retries and operators
    the words, the design, the QR  | The printer, the stock and the
    text and a finished picture    |   settings
  This example client and the spec | Everything else at your end

Everything after the collection of a badge is yours. We send nothing else, and
we want nothing back.

The full interface is in print-partner-spec.md: the announcement, the pickup,
the waiting list, every field and every error code. That file is the
reference. This file only starts you.


WORDS WE USE
------------
  announcement   The UDP message on port 8632 that tells you that a badge is
                 ready. Section 1 of the spec calls this the announcement.
  badge          The thing that you print, and also the data for it.
  job id         The id of the hub for one offer of a badge ("id").
  job key        The id of the desk for the badge ("jobKey").
  collector      Your system, which collects badges.
  collect        To get a badge from the hub over HTTP.
  waiting list   The list of badges that nobody collected.
  cancelled      The state of a badge that the hub stopped. Never print it.


REQUIREMENTS
------------
Python 3.10 or a later version. You install nothing else.

  macOS    Install from https://www.python.org/downloads/ ,
           or with Homebrew: brew install python
  Windows  Install from https://www.python.org/downloads/ and tick
           "Add python.exe to PATH" on the first screen.
           The "py" launcher that comes with it also works.

Check the version. Open Terminal (macOS) or Command Prompt (Windows). Then run
  python3 --version      (macOS)
  py -3 --version        (Windows)


QUICK START A - one computer, and no event
------------------------------------------
The kit contains a stand-in hub. It serves some badges with false data.
Therefore you can develop without our hardware.

  macOS
    1. Double-click start-fake-hub-mac.command. Leave the window open.
    2. Double-click start-client-mac.command. Press Enter to accept
       127.0.0.1 as the hub address.

  Windows
    1. Double-click start-fake-hub-windows.bat. Leave the window open.
    2. Double-click start-client-windows.bat. Press Enter to accept
       127.0.0.1 as the hub address.

In a few seconds the client saves each badge into the "badges" folder next to
these files. It saves <id>.png (the finished picture) and <id>.json (all of
the badge data). The client finds one badge only through its regular check of
the waiting list, therefore that badge can take about 10 seconds. The hub
cancels one badge: the client skips that badge, and that is correct. Two more
badges try to make the client print the same badge twice. The client does not
print it twice, and your system must not print it twice. Read "NEVER PRINT A
BADGE TWICE" below.

If macOS says that it cannot open the .command file, right-click the file and
choose Open. Or run the file from Terminal:  bash start-client-mac.command

Stop either window with Ctrl-C, or close the window.


QUICK START B - at the event, with the real hub
-----------------------------------------------
  1. Put a network cable into our router. FE gives you the port.
     Use a cable. Do not use Wi-Fi: Wi-Fi drops broadcasts, and Wi-Fi stops
     in a crowd. We give you the Wi-Fi details only as a fallback.
  2. FE gives you the address of the hub on the day (for example
     192.168.8.20).
  3. Start the client. Type that address when the client asks:
       macOS    double-click start-client-mac.command
       Windows  double-click start-client-windows.bat
     Or give the address directly:
       bash start-client-mac.command 192.168.8.20
       start-client-windows.bat 192.168.8.20
  4. Ask FE to send a test badge. A test badge has "test": true.

Do not run the stand-in hub at the event.


WHAT EACH FILE IS
-----------------
  README.txt                    This file.
  print-partner-spec.md         The full interface: the announcement, the
                                pickup, the waiting list, the fields and the
                                error codes.
  print-partner-client.py       A working example client. Put your own
                                printing in the function print_badge().
                                Everything else can stay as it is.
  fake-partner-hub.py           The stand-in hub, with badges that hold false
                                data. Use it only to develop.
  start-client-mac.command      Starts the client (macOS).
  start-fake-hub-mac.command    Starts the stand-in hub (macOS).
  start-client-windows.bat      Starts the client (Windows).
  start-fake-hub-windows.bat    Starts the stand-in hub (Windows).
  samples/                      Example badge data, if the kit contains it.

The launchers take optional arguments:
  start-client-*    [hub address] [hub port]    (defaults 127.0.0.1, 8631)
  start-fake-hub-*  [port]                      (default 8631)
  Windows only: add /nopause to close the window without a key press.

  badges.printed.json           The record of the client of what it printed.
                                Do not delete this file while the event runs.

To run the client directly:
  python3 print-partner-client.py --hub <address> [--port 8631] [--out badges]
                                 [--record FILE] [--forget]


NEVER PRINT A BADGE TWICE
-------------------------
Never print a badge twice. A delegate with two badges is the complaint that we
hear at the desk. The hub announces each badge three times, on every network,
and the waiting list repeats each badge every 5 seconds. Therefore you hear
about one badge five or six times in the ordinary case.

The hub gives each badge a job id ("id") and the job key of the desk
("jobKey"). The hub gives each badge to ONE collector, and it answers 409 to a
second collector. The example client keeps every job id and every job key that
it printed in badges.printed.json. It checks that file before it collects, and
again before it prints. It sends its own X-Print-Collector on every request.
Therefore a restart, a repeat announcement or a second client never prints a
badge again. Copy that behaviour.

Run ONE collector. A spare machine, or an old process that nobody stopped, is
the usual cause of two prints of everything.

A reprint, or a badge for a new day, comes with a NEW job key. It IS a new
badge, and you must print it.

--forget empties the record, therefore you can print a test badge again. Never
use --forget at an event.

Section 8a of print-partner-spec.md gives all of the detail.


FIREWALL
--------
The client must receive UDP on port 8632. It must also connect out to TCP port
8631. Your firewall must allow both.

  macOS    If macOS asks "Do you want the application Python to accept
           incoming network connections?", choose Allow. If you missed the
           question: System Settings > Network > Firewall > Options, and set
           Python to "Allow incoming connections".
  Windows  When Windows Defender Firewall asks about Python, tick
           "Private networks" and click Allow. If you missed the question:
           Control Panel > Windows Defender Firewall > Allow an app through
           Windows Defender Firewall, and tick Private for Python.
           Also set the event network as a Private network.


RULES THAT MATTER
-----------------
  - A badge that answers 410 is cancelled. Do not print it. The desk stopped
    the wait, and the desk can already print another badge.
  - The hub can announce the same badge more than one time. Print it one time.
  - We do not need a "printed" reply or a "failed" reply. Send nothing back to
    the hub.
  - A badge holds personal data. Delete the saved files after the event.


TROUBLESHOOTING
---------------
No badges arrive:
  - Is your cable in our router, and is the link light on?
  - Does the firewall block Python? Read FIREWALL above.
  - Start the client with the address of the hub (--hub <address>, or type
    the address when the client asks). The client then also checks the
    waiting list of the hub every 5 seconds. That works also when the network
    blocks the announcement.
  - "cannot reach the hub": check the address with FE. Also check that you can
    open http://<address>:8631/v1/prints in a browser.
  - "hub not ready (HTTP 409)": the hub is not yet in print partner mode. Ask
    FE to switch the mode on.
  - "hub not ready (HTTP 503)": nobody started the desk. Wait, or ask FE.

"Address already in use" with the stand-in hub:
  A second copy already runs. Close that copy, or start with another port:
  start-fake-hub-mac.command 8641 and then start-client-mac.command
  127.0.0.1 8641 (the same on Windows).

Only one program on a computer can listen for the announcement at one time. If
a different listener runs, the client still finds badges through the waiting
list.
</content>
```
