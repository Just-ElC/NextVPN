"""
Stand-ins for nmcli and ip, installed on PATH by the VPN tests.

State lives in FAKE_NM_DIR: the profiles NetworkManager holds (profiles.json),
the uplink `ip` reports (uplink.json, editable mid-test), and a log of every
call (calls.txt). FAKE_NM_FAIL names a step to fail: "add", "up" or "auth".
"""

import json
import os
import sys
from pathlib import Path

state = Path(os.environ["FAKE_NM_DIR"])
# The wrapper on PATH says which tool it is: runpy hides its own name.
tool = os.environ["FAKE_NM_TOOL"]
args = sys.argv[1:]
fail = os.environ.get("FAKE_NM_FAIL", "")

with open(state / "calls.txt", "a", encoding="utf-8") as fh:
    fh.write(json.dumps([tool, *args]) + "\n")


def profiles() -> dict:
    try:
        return json.loads((state / "profiles.json").read_text())
    except FileNotFoundError:
        return {}


def save(p: dict) -> None:
    (state / "profiles.json").write_text(json.dumps(p))


def uplink() -> dict:
    return json.loads((state / "uplink.json").read_text())


if tool == "ip":
    if args[:1] == ["-j"]:
        args = args[1:]
    family = None
    if args and args[0] in ("-4", "-6"):
        family, args = args[0], args[1:]
    u = uplink()
    if args[:2] == ["route", "show"]:
        dev = u.get("dev6" if family == "-6" else "dev")
        print(json.dumps([{"dst": "default", "dev": dev, "metric": 100}] if dev else []))
    elif args[:2] == ["addr", "show"]:
        dev = args[args.index("dev") + 1]
        info = [{"family": "inet6" if ":" in a else "inet", "local": a, "scope": "global"}
                for a in u.get("addresses", {}).get(dev, [])]
        print(json.dumps([{"ifname": dev, "addr_info": info}]))
    else:
        print("[]")
    sys.exit(0)

# nmcli
if args[:4] == ["-t", "-f", "RUNNING", "general"]:
    print("running")
elif args[:2] == ["-g", "IP4.DNS,IP6.DNS"]:
    print(" | ".join(uplink().get("dns", [])))
elif args[-2:] == ["connection", "show"]:
    for uuid, p in profiles().items():
        print(f"{p['name']}:{uuid}:{p['type']}:{p.get('device', '')}")
elif args[:2] == ["connection", "add"]:
    if fail == "auth":
        print("Error: Failed to add 'NextVPN' connection: Insufficient privileges", file=sys.stderr)
        sys.exit(4)
    if fail == "add":
        print("Error: Failed to add 'NextVPN' connection: tun.owner: invalid", file=sys.stderr)
        sys.exit(2)
    p = profiles()
    uuid = f"00000000-0000-4000-8000-{len(p) + 1:012d}"
    props = args[args.index("tun") + 1:]
    p[uuid] = {"name": props[props.index("connection.id") + 1], "type": "tun", "props": props}
    save(p)
    print(f"Connection '{p[uuid]['name']}' ({uuid}) successfully added.")
elif "up" in args and "connection" in args:
    if fail == "up":
        print("Error: Connection activation failed: IP configuration could not be reserved", file=sys.stderr)
        sys.exit(4)
    uuid = args[-1]
    p = profiles()
    p[uuid]["device"] = "nextvpn0"
    save(p)
    print("Connection successfully activated")
elif args[:2] == ["connection", "delete"]:
    p = profiles()
    p.pop(args[-1], None)
    save(p)
elif args[:2] == ["connection", "modify"] or args[:2] == ["device", "reapply"]:
    pass
else:
    print(f"fake nmcli: unhandled {args}", file=sys.stderr)
    sys.exit(1)
