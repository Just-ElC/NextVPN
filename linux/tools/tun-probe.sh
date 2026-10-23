#!/usr/bin/env bash
# TEMPORARY experiment: does the Psiphon network carry a packet tunnel for us,
# and does the bypass survive policy routing and strict reverse-path filtering?
set -uo pipefail
cd "$(dirname "$0")/../.."

ENGINE=linux/engine/psiphon-tunnel-core-x86_64
WORK=$(mktemp -d)
IFACE=$(ip route show default | awk '{print $5; exit}')
ADDR=$(ip -4 -o addr show dev "$IFACE" | awk '{print $4}' | cut -d/ -f1 | head -1)
DNS=$(resolvectl dns "$IFACE" 2>/dev/null | sed 's/.*://' | tr ' ' '\n' | grep -E '^[0-9.]+$' | paste -sd, -)
DNS=${DNS:-8.8.8.8}
echo "iface=$IFACE addr=$ADDR bypass-dns=$DNS"
uname -a
sysctl net.ipv4.conf.all.rp_filter net.ipv4.conf."$IFACE".rp_filter

echo "== direct"
curl -s --max-time 15 https://1.1.1.1/cdn-cgi/trace | grep -E '^(ip|loc)='

sudo ip tuntap add dev nvpn0 mode tun user "$(id -u)"
sudo ip addr add 198.18.0.1/30 dev nvpn0
sudo ip link set nvpn0 mtu 1500 up
ip addr show nvpn0

python3 - "$WORK" <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, "linux")
from nextvpn.core import tunnel_config, paths
from nextvpn.core.settings import AppSettings
work = Path(sys.argv[1])
text = tunnel_config.build(tunnel_config.read_base_config(paths.engine()), AppSettings(), str(work / "data"))
cfg = json.loads(text)
cfg["PacketTunnelTransparentDNSIPv4Address"] = "198.18.0.2"
(work / "data").mkdir()
(work / "cfg.json").write_text(json.dumps(cfg))
PY

start_engine() {
  : > "$WORK/notices.log"
  "$ENGINE" -config "$WORK/cfg.json" -serverList engine/server_list.dat \
    -tunDevice nvpn0 -tunBindInterface "$IFACE" -tunDNSServers "$DNS" 2> "$WORK/notices.log" &
  ENGINE_PID=$!
  for i in $(seq 1 240); do
    if grep -q '"noticeType":"Tunnels","data":{"count":1}' "$WORK/notices.log"; then
      echo "tunnel up after ${i}s"; return 0
    fi
    if ! kill -0 $ENGINE_PID 2>/dev/null; then echo "engine exited"; tail -40 "$WORK/notices.log"; return 1; fi
    sleep 1
  done
  echo "no tunnel"; return 1
}

summary() {
  grep -E '"noticeType":"(ActiveTunnel|ConnectedServerRegion|Tunnels|Alert|Error|Warning)"' "$WORK/notices.log" | cut -c1-300 | tail -25
  grep -E 'PacketTunnel|packet tunnel' "$WORK/notices.log" | cut -c1-300 | tail -10
}

trace() { curl -s --max-time 25 "$@" | grep -E '^(ip|loc|warp)='; }

start_engine || { summary; exit 1; }
sleep 3
summary

echo "== phase 1: host route 1.1.1.1 via tun"
sudo ip route add 1.1.1.1/32 dev nvpn0
trace https://1.1.1.1/cdn-cgi/trace
echo "== transparent DNS via 198.18.0.2"
dig +time=5 +tries=2 @198.18.0.2 example.com A +short
dig +time=5 +tries=2 @198.18.0.2 www.google.com AAAA +short
sudo ip route del 1.1.1.1/32 dev nvpn0

echo "== phase 2: policy routing, everything via tun"
sudo ip route add default dev nvpn0 table 51820
sudo ip rule add priority 30000 from "$ADDR" lookup main
sudo ip rule add priority 30001 lookup main suppress_prefixlength 0
sudo ip rule add priority 30002 lookup 51820
ip rule
trace https://1.1.1.1/cdn-cgi/trace
trace --resolve www.cloudflare.com:443:104.16.124.96 https://www.cloudflare.com/cdn-cgi/trace
echo "udp dns to 8.8.8.8 through tun:"; dig +time=5 +tries=2 @8.8.8.8 example.org A +short

echo "== phase 3: strict rp_filter (kernel) and NixOS-style netfilter rpfilter, then reconnect"
sudo sysctl -w net.ipv4.conf.all.rp_filter=1 net.ipv4.conf."$IFACE".rp_filter=1 net.ipv4.conf.nvpn0.rp_filter=1 >/dev/null
sudo iptables -t raw -I PREROUTING -m rpfilter --invert -j DROP
kill $ENGINE_PID; wait $ENGINE_PID 2>/dev/null
start_engine && { sleep 3; summary; trace https://1.1.1.1/cdn-cgi/trace; } || summary
sudo iptables -t raw -L PREROUTING -v -n

echo "== phase 4: without the from-rule (would strict rpfilter break the bypass?)"
sudo ip rule del priority 30000
kill $ENGINE_PID; wait $ENGINE_PID 2>/dev/null
timeout 100 bash -c "$(declare -f start_engine); ENGINE=$ENGINE WORK=$WORK IFACE=$IFACE DNS=$DNS start_engine" && echo "connected without from-rule" || echo "did not connect without from-rule (expected under strict rpfilter)"
sudo iptables -t raw -L PREROUTING -v -n

echo "== phase 5: IPv6 through the tunnel"
pkill -f "$WORK/cfg.json"; sleep 1
sudo iptables -t raw -D PREROUTING -m rpfilter --invert -j DROP
sudo ip rule add priority 30000 from "$ADDR" lookup main
sudo sysctl -w net.ipv6.conf.nvpn0.disable_ipv6=0 >/dev/null 2>&1 || true
sudo ip -6 addr add fdfe:dcba:9876::1/126 dev nvpn0 || true
sudo ip -6 route add default dev nvpn0 metric 1 || true
start_engine && { sleep 3; curl -6 -s --max-time 20 'https://[2606:4700:4700::1111]/cdn-cgi/trace' | grep -E '^(ip|loc)=' || echo "no IPv6 egress"; }

echo "== cleanup"
pkill -f "$WORK/cfg.json"
sudo ip rule del priority 30000; sudo ip rule del priority 30001; sudo ip rule del priority 30002
sudo ip link del nvpn0
grep -c . "$WORK/notices.log"
exit 0
