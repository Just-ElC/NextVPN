"""
A stand-in for psiphon-tunnel-core that speaks the same notice protocol.

It takes the same arguments as the real console client and plays one of a few
recorded behaviours, chosen by FAKE_ENGINE_SCENARIO, so the process handling
can be tested without a network or the real binary.
"""

import json
import os
import signal
import sys
import time

scenario = os.environ.get("FAKE_ENGINE_SCENARIO", "connect")
record = os.environ.get("FAKE_ENGINE_RECORD")
stopping = False


def notice(kind, **data):
    line = json.dumps({"data": data, "noticeType": kind, "timestamp": "2026-10-18T13:37:35.697Z"})
    sys.stderr.write(line + "\n")
    sys.stderr.flush()


def note(text):
    if record:
        with open(record, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")


def on_term(signum, frame):
    global stopping
    note("SIGTERM")
    stopping = True


note("ARGV " + json.dumps(sys.argv[1:]))
config = json.load(open(sys.argv[sys.argv.index("--config") + 1], encoding="utf-8"))
note("REGION " + config.get("EgressRegion", ""))
note("PLATFORM " + config.get("ClientPlatform", ""))

if scenario == "stubborn":
    signal.signal(signal.SIGTERM, lambda *_: note("SIGTERM-IGNORED"))
else:
    signal.signal(signal.SIGTERM, on_term)

if scenario == "error":
    notice("Error", message="error loading configuration file: invalid character")
    sys.exit(1)

if scenario == "panic":
    sys.stderr.write("panic: assignment to entry in nil map\n\ngoroutine 1 [running]:\nmain.main()\n")
    sys.stderr.flush()
    sys.exit(2)

notice("BuildInfo", buildDate="2026-10-05", goVersion="go1.26.8")
notice("ListeningSocksProxyPort", port=41001)
notice("ListeningHttpProxyPort", port=41002)
notice("AvailableEgressRegions", regions=["DE", "NL", "US"])
notice("ConnectingServer", ipAddress="203.0.113.1")
notice("Info", message="routine chatter")
time.sleep(0.05)
notice("ActiveTunnel", protocol="OSSH")
notice("ConnectedServerRegion", serverRegion=config.get("EgressRegion") or "NL")
notice("ClientRegion", region="RU")
notice("Tunnels", count=1)

if scenario == "redial":
    time.sleep(0.1)
    notice("Tunnels", count=0)
    time.sleep(0.2)
    notice("Tunnels", count=1)

while not stopping:
    notice("BytesTransferred", sent=512, received=4096)
    time.sleep(0.1)

notice("Tunnels", count=0)
notice("Exiting")
note("EXITED")
sys.exit(0)
