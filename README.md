Just a TCP Proxy
================

Listens for connections on one (or more) TCP port, and forward to another.
Support IPv4 and/or IPv6 addressing.

```sh
pip install https://github.com/mdavidsaver/just-tcp-proxy

# listen on ipv4 and/or ipv6 (eg. if both 127.0.0.1 and ::1 in /etc/hosts)
python3 -m just_tcp_proxy --local localhost:1234 otherhost:5678

# listen ipv4 only
python3 -m just_tcp_proxy --local 127.0.0.1:1234 otherhost:5678

# listen ipv6 only
python3 -m just_tcp_proxy --local ::1:1234 otherhost:5678
```

Alternatives
------------

* [simpletcpproxy](http://manpages.ubuntu.com/manpages/impish/man1/simpleproxy.1.html)
  if IPv6 support is not needed.  Packaged with Debian derivatives among others.
* [NGINX stream module](http://nginx.org/en/docs/stream/ngx_stream_proxy_module.html)
  if you are already running nginx.
