#!/usr/bin/env python3

import sys
import signal
import logging
import errno
import asyncio
from argparse import ArgumentParser, ArgumentError

_log = logging.getLogger(__name__)

class Proxy:
    limit = 64*1024
    def __init__(self, args):
        self.local = args.local
        self.host, self.port = args.destination
        self.timeout = args.timeout or None
        _log.info('Will forward to %s:%d', self.host, self.port)

        if not self.local:
            _log.error('Must provide at least one --local endpoint')
            sys.exit(1)

        self.evt = asyncio.Event()

    async def bind(self):
        self.servers = []
        for host, port in self.local:
            S = await asyncio.start_server(self.new_client, host=host, port=port,
                                           limit=self.limit, start_serving=True)
            self.servers.append(S)
            _log.info('Listening on %r', [S.getsockname() for S in S.sockets])

    async def shutdown(self):
        for S in self.servers:
            S.close()
        for S in self.servers:
            await S.wait_closed()

    def interrupt(self):
        self.evt.set()

    async def main(self):
        loop = asyncio.get_running_loop()
        
        await self.bind()

        loop.add_signal_handler(signal.SIGINT, self.evt.set)
        loop.add_signal_handler(signal.SIGTERM, self.evt.set)

        try:
            _log.debug('Park')
            await self.evt.wait()
        except KeyboardInterrupt:
            pass

        await self.shutdown()
        _log.debug('Done')

    async def new_client(self, sR, sW):
        cW = None
        try:
            peer = sW.get_extra_info('peername')
            _log.info('Connection from %s via %s, forward to %s:%r',
                      peer, sW.get_extra_info('sockname'),
                      self.host, self.port)

            cR, cW = await asyncio.wait_for(asyncio.open_connection(host=self.host, port=self.port, limit=self.limit),
                                            timeout=self.timeout)
            _log.debug('forwarded to %s:%d', self.host, self.port)

            sW.transport.set_write_buffer_limits(high=self.limit)
            cW.transport.set_write_buffer_limits(high=self.limit)

            s2c = asyncio.create_task(self.forward(sR, cW, 's2c'))
            c2s = asyncio.create_task(self.forward(cR, sW, 'c2s'))

            done, pending = await asyncio.wait((s2c, c2s), timeout=self.timeout)

            if not done:
                _log.error('Timeout from %s', peer)
            for t in pending:
                t.cancel()
            for t in (s2c, c2s):
                try:
                    await t
                except asyncio.CancelledError:
                    pass

        except asyncio.CancelledError:
            pass

        except:
            _log.exception('oops')

        finally:
            _log.debug('end forwarded to %s:%d', self.host, self.port)
            sW.close()
            if cW is not None:
                cW.close()
                await cW.wait_closed()
            await sW.wait_closed()

    async def forward(self, R, W, lbl):
        _log.debug('forward %s', lbl)
        while True:
            buf = await R.read(self.limit)
            _log.debug('forward %s RX %s', lbl, buf)
            if not buf:
                break

            W.write(buf)
            await W.drain()
        if not W.is_closing():
            try:
                W.write_eof()
            except OSError as e:
                # TODO: How does can we be !is_closing() but actually closed?
                #       happens when peer aborts connection.
                if e.errno!=errno.ENOTCONN:
                    raise
        _log.debug('end forward %s', lbl)

def getargs():
    def endpoint(s):
        sep = s.rfind(':')
        if sep==-1:
            raise ArgumentError('endpoint requires port number')
        return s[:sep], int(s[sep+1:])

    P = ArgumentParser()
    P.add_argument('-v', '--verbose', action='store_const', dest='level',
                   default=logging.WARN, const=logging.INFO)
    P.add_argument('-d', '--debug', action='store_const', dest='level',
                   const=logging.DEBUG)
    P.add_argument('-q', '--quiet', action='store_const', dest='level',
                   const=logging.ERROR)

    P.add_argument('-B','--bind', dest='local', action='append', type=endpoint,
                   help='Local endpoint to bind()')
    P.add_argument('-t','--timeout', type=float,
                   help='In activity timeout in seconds.  0 disables (default).')
    P.add_argument('destination', type=endpoint,
                   help='Endpoint to connect()')
    return P

async def amain(args):
    asyncio.get_running_loop().set_debug(args.level==logging.DEBUG)
    _log.debug('%r', args)
    await Proxy(args).main()

def main(args=None):
    args = getargs().parse_args(args=args)
    logging.basicConfig(level=args.level)
    asyncio.run(amain(args))
