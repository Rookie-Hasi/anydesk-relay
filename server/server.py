import os
import asyncio
import json
import logging
import websockets

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("RelayServer")

# Maps:
# client_id -> {"ws": WebSocketServerProtocol, "pin": str, "in_session_with": Optional[str]}
clients = {}

def is_ws_open(ws):
    try:
        if hasattr(ws, "state"):
            return str(ws.state).endswith("OPEN") or getattr(ws.state, "name", "") == "OPEN"
        return not getattr(ws, "closed", True)
    except Exception:
        return False

async def handle_client(websocket):
    client_id = None
    try:
        async for message in websocket:
            try:
                # Binary messages are video frames or raw data being relayed directly
                if isinstance(message, bytes):
                    if client_id and client_id in clients:
                        partner_id = clients[client_id].get("in_session_with")
                        if partner_id and partner_id in clients:
                            partner_ws = clients[partner_id]["ws"]
                            await partner_ws.send(message)
                    continue

                # JSON text messages for signaling, presence & control
                data = json.loads(message)
                msg_type = data.get("type")

                # 1. Registration (Host registers its 9-digit ID and security PIN)
                if msg_type == "register":
                    client_id = str(data.get("id")).replace(" ", "").strip()
                    pin = str(data.get("pin", "1234")).strip()
                    
                    # Store client session
                    clients[client_id] = {
                        "ws": websocket,
                        "pin": pin,
                        "in_session_with": None
                    }
                    logger.info(f"Client registered: ID={client_id}")
                    await websocket.send(json.dumps({
                        "type": "registered",
                        "id": client_id,
                        "status": "success"
                    }))

                # 2. Update PIN
                elif msg_type == "update_pin":
                    new_pin = str(data.get("pin", "")).strip()
                    if client_id and client_id in clients:
                        clients[client_id]["pin"] = new_pin
                        logger.info(f"Client {client_id} updated PIN.")

                # 3. Check online status of any remote ID (AnyDesk-style presence check)
                elif msg_type == "check_status":
                    target_id = str(data.get("target_id", "")).replace(" ", "").strip()
                    is_online = target_id in clients and is_ws_open(clients[target_id]["ws"])
                    await websocket.send(json.dumps({
                        "type": "status_response",
                        "target_id": target_id,
                        "online": is_online
                    }))

                # 4. Connection Request (Controller wants to connect to Host)
                elif msg_type == "connect_request":
                    target_id = str(data.get("target_id", "")).replace(" ", "").strip()
                    provided_pin = str(data.get("pin", "")).strip()

                    logger.info(f"Connection request: From {client_id} -> To {target_id}")

                    if target_id not in clients or not is_ws_open(clients[target_id]["ws"]):
                        await websocket.send(json.dumps({
                            "type": "connect_response",
                            "status": "error",
                            "message": f"Target ID ({target_id}) is OFFLINE."
                        }))
                        continue

                    target_info = clients[target_id]

                    # Verify Security PIN
                    if target_info["pin"] and target_info["pin"] != provided_pin:
                        logger.warning(f"Connection rejected for {target_id}: Invalid PIN entered.")
                        await websocket.send(json.dumps({
                            "type": "connect_response",
                            "status": "error",
                            "message": "Access Denied: Incorrect Security PIN."
                        }))
                        continue

                    # Establish session pairing
                    clients[client_id]["in_session_with"] = target_id
                    target_info["in_session_with"] = client_id

                    # Notify Host to begin streaming
                    await target_info["ws"].send(json.dumps({
                        "type": "start_streaming",
                        "controller_id": client_id
                    }))

                    # Notify Controller that connection is accepted
                    await websocket.send(json.dumps({
                        "type": "connect_response",
                        "status": "success",
                        "target_id": target_id
                    }))
                    logger.info(f"Session established between Controller {client_id} and Host {target_id}")

                # 5. Relay input commands (mouse, keyboard) to the Host
                elif msg_type in ("mouse_event", "key_event", "resolution_info"):
                    if client_id and client_id in clients:
                        partner_id = clients[client_id].get("in_session_with")
                        if partner_id and partner_id in clients:
                            await clients[partner_id]["ws"].send(message)

                # 6. End Session
                elif msg_type == "end_session":
                    if client_id and client_id in clients:
                        partner_id = clients[client_id].get("in_session_with")
                        clients[client_id]["in_session_with"] = None
                        if partner_id and partner_id in clients:
                            clients[partner_id]["in_session_with"] = None
                            await clients[partner_id]["ws"].send(json.dumps({
                                "type": "session_ended",
                                "by": client_id
                            }))
                        logger.info(f"Session ended between {client_id} and {partner_id}")

            except json.JSONDecodeError:
                logger.error("Failed to decode JSON message")
            except Exception as e:
                logger.error(f"Error handling message: {e}")

    except websockets.exceptions.ConnectionClosed:
        logger.info(f"Connection closed for client: {client_id}")
    finally:
        if client_id and client_id in clients:
            partner_id = clients[client_id].get("in_session_with")
            if partner_id and partner_id in clients:
                clients[partner_id]["in_session_with"] = None
                try:
                    await clients[partner_id]["ws"].send(json.dumps({
                        "type": "session_ended",
                        "by": client_id,
                        "reason": "Peer disconnected"
                    }))
                except Exception:
                    pass
            del clients[client_id]
            logger.info(f"Client {client_id} removed from active roster.")

async def main():
    host = "0.0.0.0"
    port = int(os.environ.get("PORT", 8765))
    logger.info(f"Starting AnyDesk-style Relay & Presence Server on {host}:{port}...")
    async with websockets.serve(handle_client, host, port, max_size=10 * 1024 * 1024):
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server stopped.")
