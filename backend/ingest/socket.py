"""The /ws handler: nodes in, results back out.

Frame dispatch is the whole job — a bare JSON array is a batch of samples, a JSON
object with `type` is control. Nodes connect here; the browser connects to /ws/ui,
so this handler never has to sniff what kind of client it is talking to.
"""
import json
import uuid


async def handle_node(ws, app):
    """One ESP32 / fake_node / replay_node connection."""
    conn_id = str(uuid.uuid4())
    await ws.accept()
    app.node_sockets[conn_id] = ws
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue                       # a torn frame is not worth dying over
            if isinstance(msg, dict):
                if msg.get("type") == "hello":
                    app.nodes.hello(conn_id, msg)
                    await app.push_nodes()
                continue
            if not isinstance(msg, list) or not msg:
                continue
            app.on_samples(conn_id, msg)
    except Exception:
        pass                                   # disconnect is normal, not an error
    finally:
        app.node_sockets.pop(conn_id, None)
        app.nodes.release(conn_id)
