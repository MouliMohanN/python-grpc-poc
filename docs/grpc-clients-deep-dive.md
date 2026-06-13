# Deep Dive: `api-gateway/grpc_clients.py`

## The file's job in one sentence

`grpc_clients.py` owns the two persistent gRPC connections (channels) from the gateway to the backend servers, and exposes ready-to-use stubs so any route in `main.py` can make a gRPC call without knowing anything about the transport.

---

## Line-by-line, with the "why" at each step

### The imports

```python
import grpc
from gen import notes_pb2_grpc, products_pb2_grpc
```

`grpc` is the gRPC runtime. `notes_pb2_grpc` and `products_pb2_grpc` are the **generated** files from `scripts/gen_proto.sh` — they contain the `NotesServiceStub` and `ProductsServiceStub` classes. These classes were mechanically produced from the `.proto` files; you never write them by hand.

---

### The four module-level globals

```python
_notes_channel = None
_products_channel = None
notes_stub = None
products_stub = None
```

These are intentionally module-level (Python's equivalent of a singleton). The reason: a gRPC **channel** is an expensive object — it manages the underlying HTTP/2 connection pool, TLS negotiation (even in insecure mode it still sets up the transport), load balancing state, and reconnection logic. You create it **once** at startup and reuse it for every request, exactly like a database connection pool. If you created a new channel per request, you'd be doing a full TCP + HTTP/2 handshake on every API call.

The underscore prefix on `_notes_channel` and `_products_channel` signals they're private to this module — callers should never touch the channels directly, only the stubs.

---

### `init_clients()` — what a "channel" actually is

```python
def init_clients():
    global _notes_channel, _products_channel, notes_stub, products_stub
    _notes_channel = grpc.aio.insecure_channel("localhost:50052")
    _products_channel = grpc.aio.insecure_channel("localhost:50051")
```

**`grpc.aio`** is the async variant of the gRPC library. The `aio` stands for asyncio — it integrates with Python's event loop so that when the gateway makes a gRPC call, it doesn't block the thread waiting for the network response. Instead it suspends (yields control back to the event loop) and resumes when the response arrives. This is critical because FastAPI is itself async; if you used the synchronous `grpc.insecure_channel`, the thread would block and the entire server would stop handling other HTTP requests while waiting for a gRPC response.

**`insecure_channel`** means no TLS — plaintext. Fine for localhost development. In production you'd use:

```python
grpc.aio.secure_channel(address, grpc.ssl_channel_credentials())
```

**The address string `"localhost:50052"`** is a name resolver target. At this point, no TCP connection has been made yet. gRPC is lazy — the actual connection is established on the first RPC call. The channel will also automatically reconnect if the server goes away and comes back.

What `insecure_channel` creates under the hood:

| Component | What it does |
|---|---|
| Channel state machine | Tracks `IDLE → CONNECTING → READY → TRANSIENT_FAILURE → SHUTDOWN` |
| Subchannel pool | HTTP/2 multiplexes many RPCs over one TCP connection |
| Name resolver | Watches `localhost:50052`, resolves it to an IP |
| Load balancer | For a single address this is pick-first; swap in round-robin for multiple server instances |

---

### The stub — what it is and what it does

```python
notes_stub = notes_pb2_grpc.NotesServiceStub(_notes_channel)
products_stub = products_pb2_grpc.ProductsServiceStub(_products_channel)
```

A **stub** is a local object that looks like the remote service. When you call `notes_stub.GetNote(request)`, it feels like calling a local function, but under the hood it:

1. Serialises the `GetNoteRequest` Python object → **Protobuf binary** (via `SerializeToString`)
2. Opens an HTTP/2 stream on the channel's TCP connection
3. Sends an HTTP/2 `HEADERS` frame with the gRPC path `/notes.NotesService/GetNote` and `content-type: application/grpc`
4. Sends a `DATA` frame containing the serialised bytes, prefixed with a 5-byte length header (1 compression flag byte + 4 bytes length)
5. Waits (asynchronously) for the server's response `DATA` frame
6. Deserialises the bytes back into a `Note` Python object (via `FromString`)
7. Returns that object to your `await` call

The stub is **stateless** — it holds no per-call data. It just closes over the channel and knows the method paths and serialisers for each RPC. From the generated `NotesServiceStub.__init__`:

```python
self.CreateNote  = channel.unary_unary('/notes.NotesService/CreateNote', ...)
self.GetNote     = channel.unary_unary('/notes.NotesService/GetNote', ...)
self.StreamNotes = channel.unary_stream('/notes.NotesService/StreamNotes', ...)
```

| gRPC method type | Meaning | Used for |
|---|---|---|
| `unary_unary` | one request → one response | `CreateNote`, `GetNote` |
| `unary_stream` | one request → many responses | `StreamNotes`, `StreamProducts` |

These map directly to what's declared in the `.proto` file.

---

### Why `main.py` uses `grpc_clients.notes_stub` instead of the imported name

```python
# main.py — imports the name at module load time
from grpc_clients import close_clients, init_clients, notes_stub, products_stub

# main.py — uses the module for a live lookup at call time
await grpc_clients.notes_stub.CreateNote(...)
```

This is a subtle but important Python gotcha. When you write:

```python
from grpc_clients import notes_stub
```

Python binds the local name `notes_stub` to whatever `grpc_clients.notes_stub` points to **at that moment** — which is `None`, because `init_clients()` hasn't run yet. If you then called `notes_stub.CreateNote(...)`, you'd get:

```
AttributeError: 'NoneType' object has no attribute 'CreateNote'
```

By using `grpc_clients.notes_stub` (a reference to the module object), you're doing a **live lookup** at every call — you follow the reference chain each time, so you always get the value the global was set to after `init_clients()` ran. This is why both the import and the module-qualified access coexist in `main.py`.

---

### `lifespan` — when `init_clients` is called and why

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_clients()   # runs before the server accepts any requests
    yield            # server is live here
    await close_clients()  # runs after the last request, on shutdown
```

FastAPI's `lifespan` is an async context manager that wraps the entire server lifetime. Code before `yield` is startup, after `yield` is shutdown. This guarantees:

1. Channels and stubs exist before the first HTTP request arrives — no race condition
2. Channels are cleanly closed on `Ctrl-C` — HTTP/2 sends a `GOAWAY` frame to the gRPC servers, signalling a graceful disconnect rather than a raw TCP drop

---

### `close_clients()` — why it's async

```python
async def close_clients():
    if _notes_channel:
        await _notes_channel.close()
```

`grpc.aio` channels are async objects. Closing them sends a `GOAWAY` frame over HTTP/2 and waits for any in-flight RPCs to complete or timeout. Since that involves network I/O, `close_clients` must be `async` and awaited.

---

## End-to-end flow for a single `GET /notes/{id}` call

```
Browser
  │  HTTP GET /notes/abc-123
  ▼
FastAPI (uvicorn event loop)
  │  matches route get_note()
  │  calls: await grpc_clients.notes_stub.GetNote(GetNoteRequest(id="abc-123"))
  │
  │  [suspends — yields to event loop, other requests can be handled]
  │
  ▼
grpc.aio (HTTP/2 layer)
  │  serialises GetNoteRequest → protobuf binary
  │  sends HTTP/2 HEADERS: path=/notes.NotesService/GetNote
  │  sends HTTP/2 DATA: [5-byte prefix][binary payload]
  ▼
Python gRPC server (python-server, :50052)
  │  receives frames, deserialises → GetNoteRequest object
  │  calls NotesServicer.GetNote()
  │    → checks Redis "note:abc-123"
  │    → hit or miss → returns Note proto object
  │  serialises Note → binary
  │  sends HTTP/2 DATA back
  ▼
grpc.aio (HTTP/2 layer, gateway side)
  │  receives DATA frame
  │  deserialises binary → Note Python object
  │  resumes the suspended coroutine
  ▼
FastAPI route handler
  │  returns {"id": note.id, "title": note.title, "body": note.body}
  ▼
Browser
  HTTP 200 {"id": "abc-123", "title": "...", "body": "..."}
```

The event loop **never blocks**. While the gRPC response is in-flight over the network, uvicorn is free to handle other incoming HTTP requests on the same thread.

---

## Key concepts summary

| Concept | What it means here |
|---|---|
| **Channel** | Long-lived HTTP/2 connection manager. Created once at startup, reused for every request. |
| **Stub** | Local proxy object. Looks like a function call; is actually serialise → network → deserialise. |
| **`grpc.aio`** | Async variant. Never blocks the event loop thread. Essential for FastAPI. |
| **Module-level globals** | Singleton pattern — one channel per backend server for the process lifetime. |
| **`lifespan`** | Ensures channels exist before requests arrive and are closed cleanly on shutdown. |
| **`grpc_clients.stub` vs `stub`** | Module reference does a live lookup, bypassing the `None` that was bound at import time. |
| **`insecure_channel`** | Plaintext — no TLS. Use `secure_channel` with credentials in production. |
| **Lazy connection** | No TCP connection until the first actual RPC call. Channel reconnects automatically if the server restarts. |
