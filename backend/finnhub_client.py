
import os
import asyncio
import json
import logging
from websockets import connect, ConnectionClosedError
from dotenv import load_dotenv

load_dotenv()
FINNHUB_TOKEN = os.getenv("FINNHUB_API_KEY")
FINNHUB_WS = f"wss://ws.finnhub.io?token={FINNHUB_TOKEN}"

logger = logging.getLogger("finnhub_client")
logger.setLevel(logging.INFO)

class FinnhubClient:
    def __init__(self):
        self.ws = None
        self._symbol_subscriptions = set()
        self._incoming_queue = asyncio.Queue()  # messages coming from Finnhub to app
        self._outgoing_queue = asyncio.Queue()  # subscribe/unsubscribe requests to send to Finnhub
        self._task = None
        self._connected = asyncio.Event()

    async def start(self):
        """Start background task that connects and manages incoming/outgoing traffic."""
        if self._task is None:
            self._task = asyncio.create_task(self._run_loop())

    async def _run_loop(self):
        backoff = 1
        while True:
            try:
                logger.info("Connecting to Finnhub...")
                async with connect(FINNHUB_WS, ping_interval=20, ping_timeout=10) as ws:
                    self.ws = ws
                    logger.info("Connected to Finnhub")
                    # on reconnect, re-subscribe
                    await self._resubscribe_all()

                    self._connected.set()
                    # create tasks to read and write
                    reader = asyncio.create_task(self._reader())
                    writer = asyncio.create_task(self._writer())
                    done, pending = await asyncio.wait([reader, writer], return_when=asyncio.FIRST_EXCEPTION)
                    for t in pending:
                        t.cancel()
                    # if we reach here, something crashed — loop will try reconnect
            except Exception as e:
                logger.warning("Finnhub connection failed: %s", e)
                self._connected.clear()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
            else:
                backoff = 1  # reset backoff on clean disconnect

    async def _reader(self):
        try:
            async for raw in self.ws:
                try:
                    data = json.loads(raw)
                except Exception:
                    data = {"raw": raw}
                # push to app-level queue for broadcasting
                await self._incoming_queue.put(data)
        except ConnectionClosedError as e:
            logger.warning("Finnhub reader closed: %s", e)
        except Exception as e:
            logger.exception("Finnhub reader error: %s", e)

    async def _writer(self):
        """Send outgoing subscribe/unsubscribe commands to Finnhub as they arrive."""
        try:
            while True:
                msg = await self._outgoing_queue.get()
                if not self.ws.closed:
                    await self.ws.send(json.dumps(msg))
        except ConnectionClosedError as e:
            logger.warning("Finnhub writer closed: %s", e)
        except Exception as e:
            logger.exception("Finnhub writer error: %s", e)

    async def subscribe(self, symbol: str):
        symbol = symbol.upper()
        if symbol in self._symbol_subscriptions:
            return
        self._symbol_subscriptions.add(symbol)
        await self._outgoing_queue.put({"type": "subscribe", "symbol": symbol})

    async def unsubscribe(self, symbol: str):
        symbol = symbol.upper()
        if symbol in self._symbol_subscriptions:
            self._symbol_subscriptions.remove(symbol)
            await self._outgoing_queue.put({"type": "unsubscribe", "symbol": symbol})

    async def _resubscribe_all(self):
        # called after a reconnect to re-subscribe to active symbols
        for s in list(self._symbol_subscriptions):
            await self._outgoing_queue.put({"type": "subscribe", "symbol": s})

    async def get_message(self):
        """Get next message from Finnhub (awaitable)."""
        return await self._incoming_queue.get()

    def is_connected(self):
        return self._connected.is_set()
