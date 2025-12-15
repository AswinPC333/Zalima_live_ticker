# main.py
import asyncio
import json
import logging
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Set
from finnhub_client import FinnhubClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("photon")

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

finnhub = FinnhubClient()

# Connected browser clients data structure:
# websocket -> {"subscriptions": set([...])}
clients: Dict[WebSocket, Dict] = {}

@app.on_event("startup")
async def startup_event():
    # start finnhub client background task
    await finnhub.start()
    # also start a broadcaster loop to forward messages from finnhub to browser clients
    asyncio.create_task(broadcaster())

async def broadcaster():
    """Continuously read from Finnhub client and forward to interested web clients."""
    while True:
        msg = await finnhub.get_message()
        # simple filter: Finnhub trade stream sends {"data":[{...}], "type":"trade"} etc.
        try:
            # broadcast only trade messages
            if isinstance(msg, dict) and msg.get("type") == "trade":
                for trade in msg.get("data", []):
                    symbol = trade.get("s")
                    if not symbol:
                        continue
                    # send trade only to clients subscribed to this symbol
                    for ws, meta in list(clients.items()):
                        try:
                            if symbol in meta["subscriptions"]:
                                await ws.send_text(json.dumps({"type":"trade","symbol":symbol,"data":trade}))
                        except Exception:
                            # remove dead clients
                            await disconnect_client(ws)
        except Exception:
            logger.exception("Error in broadcaster loop for message: %s", msg)

async def connect_client(websocket: WebSocket):
    await websocket.accept()
    clients[websocket] = {"subscriptions": set()}
    logger.info("Client connected. total=%d", len(clients))

async def disconnect_client(websocket: WebSocket):
    try:
        clients.pop(websocket, None)
        await websocket.close()
    except Exception:
        pass
    logger.info("Client disconnected. total=%d", len(clients))

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await connect_client(websocket)
    try:
        # Inform client about Finnhub connection status
        await websocket.send_text(json.dumps({"type":"status","connected":finnhub.is_connected()}))
        while True:
            data = await websocket.receive_text()
            # Expect JSON messages from browser, e.g. {"cmd":"subscribe","symbol":"AAPL"}
            try:
                payload = json.loads(data)
            except Exception:
                await websocket.send_text(json.dumps({"type":"error","message":"invalid json"}))
                continue

            cmd = payload.get("cmd")
            if cmd == "subscribe":
                symbol = payload.get("symbol","").upper()
                if symbol:
                    # add to client subscription set
                    clients[websocket]["subscriptions"].add(symbol)
                    # ensure finn hub is subscribed
                    await finnhub.subscribe(symbol)
                    await websocket.send_text(json.dumps({"type":"subscribed","symbol":symbol}))
            elif cmd == "unsubscribe":
                symbol = payload.get("symbol","").upper()
                if symbol:
                    clients[websocket]["subscriptions"].discard(symbol)
                    # if no clients remain subscribed to this symbol, tell finnhub to unsubscribe
                    if not any(symbol in meta["subscriptions"] for meta in clients.values()):
                        await finnhub.unsubscribe(symbol)
                    await websocket.send_text(json.dumps({"type":"unsubscribed","symbol":symbol}))
            elif cmd == "ping":
                await websocket.send_text(json.dumps({"type":"pong"}))
            else:
                await websocket.send_text(json.dumps({"type":"error","message":"unknown command"}))
    except WebSocketDisconnect:
        await disconnect_client(websocket)
    except Exception:
        await disconnect_client(websocket)
