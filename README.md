Just a TCP Proxy
================

Listens for connections on one (or more) TCP port, and forward to another.
Support IPv4 and/or IPv6 addressing.

```sh
# listen on ipv4 and/or ipv6 (eg. if both 127.0.0.1 and ::1 in /etc/hosts)
python3 -m just_tcp_proxy --local localhost:1234 otherhost:5678

# listen ipv4 only
python3 -m just_tcp_proxy --local 127.0.0.1:1234 otherhost:5678

# listen ipv4 only
python3 -m just_tcp_proxy --local ::1:1234 otherhost:5678
```
