# Deep Dive: Pure Reflection Gateway

## What it is

In the stub-based model the gateway imports generated Python files (`notes_pb2.py`, `notes_pb2_grpc.py`) and calls typed stub methods. Those files are produced by `gen_proto.sh` and must be regenerated every time a `.proto` changes.

In the pure reflection model the gateway has **no generated code at all**. On startup it connects to each gRPC server, queries the reflection API to fetch the live schema, loads it into an in-memory descriptor pool, and builds message classes dynamically. From that point on it can serialise and deserialise any message and call any RPC — with zero `.proto` files and zero codegen.

The two files that implement this in the project:

| File | Role |
|---|---|
| `api-gateway/grpc_clients_v2.py` | Reflection bootstrap + dynamic call helpers |
| `api-gateway/main.py` | FastAPI routes — no `pb2` imports anywhere |

`api-gateway/grpc_clients.py` is kept as a reference showing the original stub-based version.

---

## What the gateway no longer needs

| Thing | Stub-based | Pure reflection |
|---|---|---|
| `api-gateway/gen/` directory | Required — imported by routes | Not imported — ignored |
| `gen_proto.sh` for gateway | Required after every proto change | Not needed |
| `notes_pb2`, `products_pb2` imports | Required | Removed |
| `notes_pb2_grpc.NotesServiceStub` | Required | Removed |
| Both servers running at gateway startup | Not required | **Required** |

`gen_proto.sh` still runs for `python-server` and `go-server` — they implement and serve RPCs using generated code. Only the gateway is stub-free.

---

## Startup flow

```
Gateway starts
  │
  ├── _register("notes", "localhost:50052")
  │     │
  │     ├── grpc.aio.insecure_channel("localhost:50052")
  │     │
  │     ├── _list_services(channel)
  │     │     └── reflection: list_services → ["notes.NotesService"]
  │     │
  │     ├── _fetch_file_descriptors(channel, "notes.NotesService")
  │     │     └── reflection: file_containing_symbol
  │     │           → [FileDescriptorProto bytes for notes.proto]
  │     │
  │     └── _build_pool([fd_bytes, ...])
  │           └── DescriptorPool.Add(FileDescriptorProto) for each file
  │
  ├── _register("products", "localhost:50051")
  │     └── (same flow → loads products.proto into its own pool)
  │
  └── FastAPI starts accepting HTTP requests
```

If either server is unreachable at startup, the reflection query fails and the gateway exits with `StatusCode.UNAVAILABLE`. This is intentional — it fails loudly rather than starting in a broken state.

---

## `grpc_clients_v2.py` — line by line

### Service registry

```python
_services: dict = {}
```

A module-level dict keyed by alias (`"notes"`, `"products"`). Each entry holds everything the gateway needs to make calls to that server:

```python
_services["notes"] = {
    "address":       "localhost:50052",
    "channel":       grpc.aio.insecure_channel("localhost:50052"),
    "pool":          DescriptorPool(),   # loaded with notes.proto schema
    "service_names": ["notes.NotesService"],
}
```

### `_list_services` — discover what a server exposes

```python
async def _list_services(channel) -> list[str]:
    stub = reflection_pb2_grpc.ServerReflectionStub(channel)

    async def _req():
        yield reflection_pb2.ServerReflectionRequest(list_services="")

    names = []
    async for resp in stub.ServerReflectionInfo(_req()):
        if resp.HasField("list_services_response"):
            for svc in resp.list_services_response.service:
                if svc.name != "grpc.reflection.v1alpha.ServerReflection":
                    names.append(svc.name)
    return names
```

`ServerReflectionInfo` is a bidirectional streaming RPC. We send one `list_services` request and read one `list_services_response` back. The reflection service itself is filtered out — we only want the application services.

### `_fetch_file_descriptors` — get the schema bytes

```python
async def _fetch_file_descriptors(channel, service_name: str) -> list[bytes]:
    stub = reflection_pb2_grpc.ServerReflectionStub(channel)

    async def _req():
        yield reflection_pb2.ServerReflectionRequest(
            file_containing_symbol=service_name
        )

    fd_bytes_list = []
    async for resp in stub.ServerReflectionInfo(_req()):
        if resp.HasField("file_descriptor_response"):
            fd_bytes_list.extend(resp.file_descriptor_response.file_descriptor_proto)
    return fd_bytes_list
```

`file_containing_symbol` asks: "give me the `.proto` file that defines `notes.NotesService`, plus all its transitive imports." The server responds with a list of serialised `FileDescriptorProto` bytes — one per `.proto` file. This is byte-for-byte identical to what `protoc --descriptor_set_out` produces at build time.

### `_build_pool` — load schema into memory

```python
def _build_pool(all_fd_bytes: list[bytes]) -> descriptor_pool.DescriptorPool:
    pool = descriptor_pool.DescriptorPool()
    added = set()
    for fd_bytes in all_fd_bytes:
        fd = descriptor_pb2.FileDescriptorProto.FromString(fd_bytes)
        if fd.name not in added:
            pool.Add(fd)
            added.add(fd.name)
    return pool
```

`DescriptorPool` is Python's in-memory schema registry. `Add()` registers one `FileDescriptorProto` — after this the pool knows every message type, field name, field number, and service method that was in the `.proto`. The `added` set guards against duplicate files (transitive imports can appear multiple times across different service requests).

### `_resolve_method` — look up a method at call time

```python
def _resolve_method(alias: str, service_name: str, method_name: str):
    pool     = _services[alias]["pool"]
    svc_desc = pool.FindServiceByName(service_name)   # e.g. "notes.NotesService"
    mth_desc = svc_desc.FindMethodByName(method_name) # e.g. "CreateNote"
    ReqClass  = message_factory.GetMessageClass(mth_desc.input_type)
    RespClass = message_factory.GetMessageClass(mth_desc.output_type)
    return mth_desc, ReqClass, RespClass
```

`GetMessageClass` returns a fully usable Python class constructed at runtime from the descriptor — equivalent to the `notes_pb2.CreateNoteRequest` class that `gen_proto.sh` would have generated. You can instantiate it, set fields, and call `SerializeToString()` on it, just like a generated class.

### `call_unary` — make a unary RPC

```python
async def call_unary(alias: str, service_name: str, method_name: str, data: dict) -> dict:
    mth_desc, ReqClass, RespClass = _resolve_method(alias, service_name, method_name)
    channel = _services[alias]["channel"]

    rpc = channel.unary_unary(
        f"/{service_name}/{method_name}",
        request_serializer=ReqClass.SerializeToString,
        response_deserializer=RespClass.FromString,
    )
    response = await rpc(ReqClass(**data))
    return MessageToDict(response, preserving_proto_field_name=True,
                         including_default_value_fields=True)
```

`channel.unary_unary` creates a raw callable for one RPC path. We pass:
- `request_serializer` — how to turn the request object into wire bytes
- `response_deserializer` — how to turn wire bytes back into a Python object

`ReqClass(**data)` constructs the request from a plain dict — `{"title": "hello", "body": "world"}` becomes a `CreateNoteRequest` with those fields set.

`MessageToDict` converts the protobuf response object into a plain Python dict that FastAPI can serialise to JSON. `preserving_proto_field_name=True` keeps `snake_case` field names (without it, protobuf would convert them to `camelCase`). `including_default_value_fields=True` ensures zero-value fields like `{"deleted": 0}` are included rather than omitted.

### `call_server_stream` — consume a streaming RPC

```python
async def call_server_stream(alias, service_name, method_name, data):
    mth_desc, ReqClass, RespClass = _resolve_method(alias, service_name, method_name)
    channel = _services[alias]["channel"]

    rpc = channel.unary_stream(
        f"/{service_name}/{method_name}",
        request_serializer=ReqClass.SerializeToString,
        response_deserializer=RespClass.FromString,
    )
    async for response in rpc(ReqClass(**data)):
        yield MessageToDict(response, preserving_proto_field_name=True,
                            including_default_value_fields=True)
```

Same pattern as `call_unary` but uses `channel.unary_stream` and is an async generator. The caller iterates it with `async for` and gets one dict per streamed message.

---

## `main.py` — what changed

Before (stub-based):

```python
from gen import notes_pb2, products_pb2
import grpc_clients

# route body
resp = await grpc_clients.notes_stub.CreateNote(
    notes_pb2.CreateNoteRequest(title=req.title, body=req.body)
)
return {"id": resp.id}
```

After (pure reflection):

```python
import grpc_clients_v2 as grpc_clients

# route body
return await grpc_clients.call_unary(
    "notes", "notes.NotesService", "CreateNote",
    {"title": req.title, "body": req.body},
)
```

No `pb2` imports. No stub attribute access. The route just describes what it wants to call and passes a plain dict. The dynamic layer handles everything else.

The lifespan changed from sync to async init:

```python
# before
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_clients()      # sync — just opened channels
    yield
    await close_clients()

# after
@asynccontextmanager
async def lifespan(app: FastAPI):
    await grpc_clients.init_clients()   # async — queries reflection
    yield
    await grpc_clients.close_clients()
```

---

## Adding a new RPC — what changes

With generated stubs: add to proto → run `gen_proto.sh` → update gateway route → restart gateway.

With pure reflection: add to proto → run `gen_proto.sh` for the **server only** → restart the server → add a gateway route → restart the gateway.

The gateway route body is the same pattern regardless of what the RPC does:

```python
@app.post("/notes/search")
async def search_notes(req: SearchRequest):
    return await grpc_clients.call_unary(
        "notes", "notes.NotesService", "SearchNotes",
        {"query": req.query},
    )
```

No `notes_pb2.SearchNotesRequest` import needed. The descriptor pool already knows about `SearchNotes` the moment the server is restarted with the new stub.

---

## Key concepts summary

| Concept | What it means |
|---|---|
| `DescriptorPool` | In-memory registry of all protobuf types — loaded from reflection response bytes at startup |
| `FileDescriptorProto` | Compiled binary representation of one `.proto` file — what the reflection API returns |
| `file_containing_symbol` | Reflection request that returns the full schema for a named service including all transitive imports |
| `message_factory.GetMessageClass` | Returns a usable Python message class built at runtime from a descriptor — no generated `_pb2.py` needed |
| `channel.unary_unary` / `channel.unary_stream` | Raw channel calls that bypass stubs — take serialiser/deserialiser functions instead of a typed stub method |
| `MessageToDict` | Converts a protobuf message object to a plain Python dict for JSON serialisation |
| `preserving_proto_field_name` | Keeps `snake_case` field names in the dict output (default would convert to `camelCase`) |
| `including_default_value_fields` | Includes zero-value fields (`0`, `""`, `false`) in the dict — without this they are omitted |
| Startup dependency | Gateway must start after all servers — it queries reflection live and fails immediately if a server is down |
