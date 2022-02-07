
import asyncio
import errno
import logging
import socket
import unittest
import warnings

from .util import AIOTest

from .. import (Proxy, getargs as _getargs)

def can_ipv6():
    """Probe for build, OS, and admin support/configuration for IPv6.

    AF_INET6 missing if OS/libc not built with ipv6
    socket() fails if OS kernel ipv6 support not include, or disabled.
    bind() fails if loopback interface not configured for ipv6, which we
    interpret as an admin decision to inhibit.
    """
    if hasattr(socket, 'AF_INET6'):
        try:
            with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as S:
                S.bind(('::1',0))
                return True
        except OSError as e:
            if e.errno not in (errno.EAFNOSUPPORT, errno.EADDRNOTAVAIL):
                warnings.warn('Unexpected errno while probing for ipv6 support %s', e)
    return False

_log = logging.getLogger(__name__)

def getargs(args):
    try:
        return _getargs().parse_args(args)
    except SystemExit:
        # can't safely raise SystemExit from coroutine...
        # asyncio doesn't handle BaseException well (as of py3.9)
        raise RuntimeError('oop')

class TestNoop(AIOTest):
    async def test_idle(self):
        args = getargs(['-d', '--bind', '127.0.0.1:0', '127.0.0.1:5432'])
        dut = Proxy(args)
        await dut.bind()

        addrs = [sock.getsockname() for serv in dut.servers for sock in serv.sockets]
        self.assertEqual(1, len(addrs), msg=addrs)

        await dut.shutdown()

class ProxyTester:
    def __init__(self, upstream_cb, iface = '127.0.0.1'):
        self.upstream_cb, self.iface = upstream_cb, iface

    async def __aenter__(self):
        self.upstream = await asyncio.start_server(self.upstream_cb,
                                                   host=self.iface, port=0,
                                                   start_serving=True)
        self.us = [S.getsockname() for S in self.upstream.sockets]
        _log.debug('upstream %r', self.upstream)
        host, port = self.us[0][:2]

        args = getargs(['-d', '--bind', self.iface+':0', f'{host}:{port}'])
        self.proxy = Proxy(args)

        await self.proxy.bind()
        self.ps = [S.getsockname() for serv in self.proxy.servers for S in serv.sockets]
        _log.debug('proxy servers %r', self.proxy.servers)
        host, port = self.ps[0][:2]

        _log.debug('Downstream connecting...')
        self.R, self.W = await asyncio.open_connection(host=host, port=port)
        _log.debug('Downstream connected')

        return self

    async def __aexit__(self,A,B,C):
        _log.debug('Downstream close')
        self.W.close()
        await self.W.wait_closed()
        _log.debug('proxy close')
        await self.proxy.shutdown()
        _log.debug('upstream close')
        # can trigger "assert self._sockets is not None" failure
        # due to race with pending accept()ing Task
        self.upstream.close()
        await self.upstream.wait_closed()

async def readall(R):
    Bs = []
    while True:
        B = await R.read()
        _log.debug('readall %r', B)
        if not B:
            break
        Bs.append(B)
    return b''.join(Bs)

class TestProxy(AIOTest):
    iface = '127.0.0.1'

    async def test_say_hello(self):
        RX = []
        async def say_hello(R, W):
            _log.debug('Connection to upstream')
            W.write(b'hello')
            await W.drain()
            _log.debug('Said hello')
            W.write_eof()

            while True:
                B = await R.read()
                if not B:
                    break
                RX.append(B)
                _log.debug('RX %r', B)

            _log.debug('End Connection to upstream')
            W.close()
            await W.wait_closed()

        async with ProxyTester(say_hello, iface=self.iface) as T:
            T.W.write_eof()
            R = await readall(T.R)
            self.assertEqual(R, b'hello')

        self.assertListEqual(RX, [])

    async def test_hear_hello(self):
        RX = []
        async def say_hello(R, W):
            _log.debug('Connection to upstream')
            W.write_eof()

            while True:
                B = await R.read()
                if not B:
                    break
                RX.append(B)
                _log.debug('upstream RX %r', B)

            _log.debug('End Connection to upstream')
            W.close()
            await W.wait_closed()

        async with ProxyTester(say_hello, iface=self.iface) as T:
            T.W.write(b'hello')
            T.W.write_eof()
            await T.W.drain()
            R = await readall(T.R)
            self.assertEqual(R, b'')

        self.assertEqual(b''.join(RX), b'hello')

    async def test_abort_upstream(self):
        async def say_nothing(R, W):
            _log.debug('Connection to upstream')
            W.close()

        async with ProxyTester(say_nothing, iface=self.iface) as T:
            T.W.write(b'lost')
            T.W.write_eof()
            await T.W.drain()
            R = await readall(T.R)
            self.assertEqual(R, b'')

    async def test_abort_downstream(self):
        connected = asyncio.Event()

        async def say_echo(R, W):
            _log.debug('Connection to upstream')
            connected.set()
            while True:
                B = await R.read()
                if not B:
                    break
                W.write(B)
                await W.drain()

        async with ProxyTester(say_echo, iface=self.iface) as T:
            await connected.wait()
            T.W.write(b'lost')
            T.W.write_eof()
            await T.W.drain()
            T.W.close()

if not can_ipv6():
    def test_noipv6():
        raise unittest.SkipTest("No IPv6 support")
else:
    class TestProxy6(TestProxy):
        iface = '::1'
