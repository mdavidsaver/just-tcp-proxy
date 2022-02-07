
import asyncio
import logging
import os
import signal
import threading
import unittest
from functools import wraps

__all__ = (
    'AIOTest',
    'WorkerLoop',
)

_log = logging.getLogger(__name__)

class AIOTestMeta(type):
    """Wraps any test*() coroutine methods to be run in the worker loop
    """
    def __new__(klass, name, bases, classdict):
        for name, mem in classdict.items():
            if name.startswith('test') and asyncio.iscoroutinefunction(mem):
                @wraps(mem)
                def _inloop(self, mem=mem):
                    self.worker(asyncio.wait_for(mem(self), timeout=self.timeout))
                classdict[name] = _inloop

        return type.__new__(klass, name, bases, classdict)

class AIOTest(unittest.TestCase, metaclass=AIOTestMeta):
    timeout = float(os.environ.get('JTP_TEST_TIMEOUT', '1.0'))

    def setUp(self):
        super().setUp()
        self.worker = WorkerLoop(timeout=self.timeout, debug=True)
        self.worker(self.setUpAsync())

    async def setUpAsync(self):
        _log.debug("setUpAsync()")

    async def tearDownAsync(self):
        _log.debug("tearDownAsync()")

    def tearDown(self):
        coro = self.tearDownAsync()
        self.assertIsNotNone(coro, msg=self.tearDownAsync)
        self.worker(coro)
        self.worker.close()
        super().tearDown()

class WorkerLoop:
    """Runs an asyncio loop in a worker thread.  Use call() or __call__() to submit work.
    Must be explicitly close()'d as GC will not collect due to references held by worker.
    """
    __all_loops = set()

    def __init__(self, *, timeout=None, debug=False):
        self.debug = debug
        self.timeout = timeout
        rdy = threading.Event()
        self._T = threading.Thread(target=asyncio.run,
                         args=(self.__run(rdy),),
                         kwargs=dict(debug=debug),
                         name=__name__,
                         daemon=True)
        self._T.start()
        rdy.wait()
        self.__all_loops.add(self)
        assert self.__close is not None
        _log.debug("Started %r", self)

    def __enter__(self):
        return self
    def __exit__(self,A,B,C):
        self.close()

    def close(self):
        """Stop loop and block to join worker thread.
        """
        if self._T is not None:
            _log.debug("Stopping %r", self)
            self.__loop.call_soon_threadsafe(self.__close)
            self._T.join()
            self._T = None
            self.__all_loops.remove(self)
            _log.debug("Stopped %r", self)

    async def __run(self, rdy): # we are called via asyncio.run()
        done = asyncio.Event()
        self.__close = done.set
        self.__loop = asyncio.get_running_loop()
        _log.debug("Begin loop %r w/ %r", self, self.__loop)

        if hasattr(signal, 'pthread_sigmask'):
            # try to force signal delivery to main()
            signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM})

        rdy.set() # allow ctor to complete
        del rdy

        try:
            await done.wait() # park to keep loop alive while handling work
        finally:
            _log.debug("End loop %r", self)

    def call(self, coro):
        """Submit work and return an concurrent.futures.Future
        """
        assert asyncio.iscoroutine(coro), coro
        return asyncio.run_coroutine_threadsafe(
            coro,
            self.__loop,
        )

    def __call__(self, coro, *, timeout=None):
        """Submit work and block until completion
        """
        return self.call(coro).result(timeout or self.timeout)

    @classmethod
    def _stop_worker_loops(klass):
        for L in klass.__all_loops.copy():
            L.close()
        assert klass.__all_loops==set(), klass.__all_loops
