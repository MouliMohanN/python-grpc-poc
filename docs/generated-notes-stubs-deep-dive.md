# Deep Dive: `api-gateway/gen/` — Generated Notes Stubs

The two files `notes_pb2.py` and `notes_pb2_grpc.py` are **never written by hand**. They are produced by running `scripts/gen_proto.sh`, which invokes `protoc` (the protobuf compiler) against `proto/notes.proto`. Understanding what they contain — and why — demystifies the entire gRPC contract.

---

## The origin: `proto/notes.proto`

Everything in the generated files traces back to this source:

```protobuf
syntax = "proto3";
package notes;

service NotesService {
  rpc CreateNote  (CreateNoteRequest)  returns (CreateNoteResponse);
  rpc GetNote     (GetNoteRequest)     returns (Note);
  rpc StreamNotes (StreamNotesRequest) returns (stream Note);
}

message Note               { string id = 1; string title = 2; string body = 3; }
message CreateNoteRequest  { string title = 1; string body = 2; }
message CreateNoteResponse { string id = 1; }
message GetNoteRequest     { string id = 1; }
message StreamNotesRequest {}
```

`protoc` reads this and produces **two separate files** because they serve different concerns:

| File | Produced by | Contains |
|---|---|---|
| `notes_pb2.py` | `protoc` (protobuf plugin) | Message classes — serialisation and deserialisation |
| `notes_pb2_grpc.py` | `protoc` (grpc plugin) | Service glue — stub, servicer, and registration |

---

## `notes_pb2.py` — the message layer

### What it does

This file teaches Python how to turn your `.proto` messages into bytes and back. Every time a request leaves the gateway or a response arrives, this code runs.

### The runtime version guard

```python
_runtime_version.ValidateProtobufRuntimeVersion(
    _runtime_version.Domain.PUBLIC,
    5, 28, 1, '',
    'notes.proto'
)
```

Protobuf's generated code is tightly coupled to the version of the runtime library it was compiled with. This guard runs at import time and raises immediately if the installed `protobuf` package is incompatible with the version of `protoc` that generated this file. It prevents silent data corruption that would happen if you tried to use mismatched serialisation logic.

### The DESCRIPTOR — the schema in binary form

```python
DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(b'\n\x0bnotes.proto\x12\x05notes\"/ ...')
```

This is the most important line in the file. That long `b'...'` byte string is a **binary-encoded copy of the entire `notes.proto` schema** — all five messages and the service definition, serialised as a `FileDescriptorProto` (which is itself a protobuf message). It was embedded at code-generation time so the runtime never needs the original `.proto` file on disk.

What the runtime does with it:

1. Parses the binary schema and registers it in the global `_descriptor_pool` — a registry of all known message types
2. From the descriptor, constructs Python classes for each message (`Note`, `CreateNoteRequest`, etc.)
3. Each class gets `SerializeToString()` and `FromString()` methods that know the exact wire format for that message

You can decode what's in that binary blob yourself — it describes fields by their **tag numbers** (the `= 1`, `= 2`, `= 3` in the proto). For example, `Note` has three fields: `id` is tag 1, `title` is tag 2, `body` is tag 3. The receiver uses tag numbers — not field names — to decode, which is why adding a new field is backwards-compatible but changing a tag number is not. See the [Protobuf wire format](#protobuf-wire-format-how-fields-become-bytes) section below for a full breakdown of how this encoding works.

### The builder calls

```python
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, _globals)
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, 'notes_pb2', _globals)
```

These two calls materialise the descriptor into live Python classes and inject them into the module's global namespace. After this runs, `notes_pb2.Note`, `notes_pb2.CreateNoteRequest`, etc. all exist as proper Python classes. Without these calls, the DESCRIPTOR would just be inert metadata.

### The serialized byte offsets

```python
_globals['_NOTE']._serialized_start=22
_globals['_NOTE']._serialized_end=69
_globals['_CREATENOTEREQUEST']._serialized_start=71
...
```

These numbers tell the runtime exactly where each message's descriptor lives inside the `DESCRIPTOR` binary blob — it's an index into the byte string. Instead of re-parsing the entire blob each time it needs to look up `Note`, the runtime can slice directly to byte 22–69. A performance optimisation baked in at generation time.

### What you get to use from this file

After import, you construct messages like normal Python objects:

```python
from gen import notes_pb2

req = notes_pb2.GetNoteRequest(id="abc-123")
# req.id == "abc-123"

# Serialise to bytes (what goes over the wire)
wire_bytes = req.SerializeToString()
# b'\n\x07abc-123'  ← field tag 1, length 7, then the string

# Deserialise back
decoded = notes_pb2.GetNoteRequest.FromString(wire_bytes)
# decoded.id == "abc-123"
```

You never call `SerializeToString` or `FromString` yourself in application code — the stub and servicer do it automatically. But they exist on every message class.

---

## `notes_pb2_grpc.py` — the service layer

This file contains three distinct things: a **Stub** (for clients), a **Servicer** (for servers), and a **registration function**. In the gateway, only the Stub is used. The Servicer and registration function are used in `python-server/`.

### Version guard

```python
GRPC_GENERATED_VERSION = '1.68.1'
GRPC_VERSION = grpc.__version__
if _version_not_supported:
    raise RuntimeError(...)
```

Same idea as `notes_pb2.py` — fails fast at import time if the `grpcio` library version doesn't match what the code was generated with. This catches the classic "I upgraded grpcio but forgot to regenerate" mistake.

### `NotesServiceStub` — the client proxy (used by the gateway)

```python
class NotesServiceStub(object):
    def __init__(self, channel):
        self.CreateNote = channel.unary_unary(
            '/notes.NotesService/CreateNote',
            request_serializer=notes__pb2.CreateNoteRequest.SerializeToString,
            response_deserializer=notes__pb2.CreateNoteResponse.FromString,
            _registered_method=True)

        self.GetNote = channel.unary_unary(
            '/notes.NotesService/GetNote',
            request_serializer=notes__pb2.GetNoteRequest.SerializeToString,
            response_deserializer=notes__pb2.Note.FromString,
            _registered_method=True)

        self.StreamNotes = channel.unary_stream(
            '/notes.NotesService/StreamNotes',
            request_serializer=notes__pb2.StreamNotesRequest.SerializeToString,
            response_deserializer=notes__pb2.Note.FromString,
            _registered_method=True)
```

Each attribute on the stub (`CreateNote`, `GetNote`, `StreamNotes`) is a **callable bound to the channel** with:

- The **full method path** — `/notes.NotesService/CreateNote`. This is the URL path in the HTTP/2 request. The format is always `/<package>.<ServiceName>/<MethodName>`. The `notes` prefix comes from `package notes;` in the proto.
- A **request serialiser** — `CreateNoteRequest.SerializeToString`. This is called just before the bytes go onto the wire.
- A **response deserialiser** — `CreateNoteResponse.FromString`. This is called on the raw bytes received from the server to reconstruct a Python object.

The method type differs per RPC:

| RPC | Channel method | What it means |
|---|---|---|
| `CreateNote` | `unary_unary` | one request → one response, then done |
| `GetNote` | `unary_unary` | one request → one response, then done |
| `StreamNotes` | `unary_stream` | one request → the server sends back N responses over an open HTTP/2 stream, then closes it |

When you call `await notes_stub.GetNote(GetNoteRequest(id="abc"))` in the gateway, this is the sequence:

```
1. GetNoteRequest(id="abc") constructed in Python
2. .SerializeToString() → b'\n\x03abc'  (protobuf wire bytes)
3. HTTP/2 HEADERS frame sent: path=/notes.NotesService/GetNote
4. HTTP/2 DATA frame sent: [5-byte gRPC prefix][b'\n\x03abc']
5. ... network round trip to python-server:50052 ...
6. HTTP/2 DATA frame received: [5-byte gRPC prefix][response bytes]
7. .FromString(response_bytes) → Note(id="...", title="...", body="...")
8. Python Note object returned to the awaiting coroutine
```

The 5-byte gRPC prefix is: 1 byte compression flag (0 = not compressed) + 4 bytes big-endian message length. This wrapping is the gRPC framing layer on top of HTTP/2.

`_registered_method=True` tells the channel that this method is pre-registered (known at channel creation time) rather than dynamically looked up. This enables a small optimisation in the gRPC runtime's method dispatch.

### `NotesServiceServicer` — the server base class (used by `python-server/`, not the gateway)

```python
class NotesServiceServicer(object):
    def CreateNote(self, request, context):
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        raise NotImplementedError('Method not implemented!')
    ...
```

This is the abstract base that `python-server/server.py`'s `NotesServicer` inherits from (implicitly — Python doesn't enforce it, but the pattern is identical to an abstract class). Every method defaults to `UNIMPLEMENTED` so that if you add a new RPC to the proto and forget to implement it, clients get a proper gRPC error rather than a crash.

The `context` parameter is the gRPC service context — it gives the server access to:
- `context.abort(code, details)` — cancel the RPC with a status code
- `context.set_trailing_metadata(...)` — attach metadata to the response
- `context.peer()` — the client's address
- `context.is_active()` — whether the client is still connected (useful in streaming)

### `add_NotesServiceServicer_to_server` — the registration function (used by `python-server/`)

```python
def add_NotesServiceServicer_to_server(servicer, server):
    rpc_method_handlers = {
        'CreateNote': grpc.unary_unary_rpc_method_handler(
            servicer.CreateNote,
            request_deserializer=notes__pb2.CreateNoteRequest.FromString,
            response_serializer=notes__pb2.CreateNoteResponse.SerializeToString,
        ),
        ...
    }
    generic_handler = grpc.method_handlers_generic_handler('notes.NotesService', rpc_method_handlers)
    server.add_generic_rpc_handlers((generic_handler,))
    server.add_registered_method_handlers('notes.NotesService', rpc_method_handlers)
```

Notice the serialiser/deserialiser direction is **mirrored** compared to the stub. On the server:

- Incoming request bytes → `FromString` (deserialise into Python object for the handler)
- Handler's returned Python object → `SerializeToString` (serialise into bytes to send back)

On the client (stub):
- Python object → `SerializeToString` (serialise to send)
- Incoming response bytes → `FromString` (deserialise into Python object)

This is called once in `python-server/server.py`:

```python
notes_pb2_grpc.add_NotesServiceServicer_to_server(servicer, server)
```

It wires the concrete `NotesServicer` implementation to the gRPC server's routing table so that when a request arrives at `/notes.NotesService/CreateNote`, the server knows to call `servicer.CreateNote(request, context)`.

### `NotesService` — the experimental static API (not used here)

```python
class NotesService(object):
    @staticmethod
    def CreateNote(request, target, ...):
        return grpc.experimental.unary_unary(request, target, '/notes.NotesService/CreateNote', ...)
```

This is an alternative client API that doesn't require creating a channel object first — you pass the `target` address directly per call. It's marked `EXPERIMENTAL` and not suitable for production because it creates a new connection per call (no channel reuse). It's not used anywhere in this project. The comment `# This class is part of an EXPERIMENTAL API` in the generated file is the signal to ignore it.

---

## How the two files relate to each other

```
notes.proto
    │
    ▼ protoc
    │
    ├─► notes_pb2.py          ← Message definitions (Note, CreateNoteRequest, ...)
    │       │                    Each message: SerializeToString() + FromString()
    │       │
    └─► notes_pb2_grpc.py     ← Service glue, imports notes_pb2
            │
            ├─► NotesServiceStub      (gateway uses this — sends RPCs)
            ├─► NotesServiceServicer  (python-server uses this — handles RPCs)
            └─► add_NotesServiceServicer_to_server  (python-server registration)
```

`notes_pb2_grpc.py` depends on `notes_pb2.py` for the serialisers and message classes — that's the `from . import notes_pb2 as notes__pb2` at the top. They are always generated and used as a pair.

---

## Protobuf wire format — how fields become bytes

This explains exactly what `SerializeToString()` produces and what `FromString()` consumes.

### Field names disappear at compile time

The `= 1`, `= 2`, `= 3` in the proto are **field tag numbers** — not default values, not array indices. They are the only identifiers that survive into the binary output. Field names (`id`, `title`, `body`) exist only in the `.proto` file and the generated Python/Go code. They are completely absent from the wire.

### Wire types — the type system on the wire

Protobuf defines 6 wire types. Each tells the decoder how many bytes to read for that field's value:

| Wire type | Value | Used for |
|---|---|---|
| VARINT | 0 | `int32`, `int64`, `bool`, `enum` |
| I64 | 1 | `fixed64`, `double` |
| LEN | 2 | `string`, `bytes`, embedded messages, repeated fields |
| I32 | 5 | `fixed32`, `float` |

`string` uses wire type **2** (LEN = length-delimited) because the decoder can't know the string's length in advance — it could be 3 bytes or 3000. So the format prefixes the value with its length.

### The tag byte: `(tag << 3 | wire_type)`

Every field on the wire starts with a tag byte that encodes **two things at once** — which field this is, and how to read its value:

```
tag_byte = (field_tag << 3) | wire_type
```

`<< 3` is a left bit-shift by 3 positions (same as multiplying by 8). It moves the tag number into the upper bits, leaving the bottom 3 bits free to hold the wire type (values 0–5 only need 3 bits).

For the `Note` message:

| Field | Tag | Wire type | Calculation | Decimal | Hex |
|---|---|---|---|---|---|
| `id` | 1 | 2 | `(1 << 3) \| 2` = `8 \| 2` | 10 | `0x0a` |
| `title` | 2 | 2 | `(2 << 3) \| 2` = `16 \| 2` | 18 | `0x12` |
| `body` | 3 | 2 | `(3 << 3) \| 2` = `24 \| 2` | 26 | `0x1a` |

In binary, you can see the split directly:

```
id tag:    00001 010   ← top 5 bits = tag 1, bottom 3 bits = wire type 2
title tag: 00010 010   ← top 5 bits = tag 2, bottom 3 bits = wire type 2
body tag:  00011 010   ← top 5 bits = tag 3, bottom 3 bits = wire type 2
```

### Length-delimited encoding for strings

For wire type 2 (LEN), after the tag byte the layout is:

```
[tag_byte] [length as varint] [raw UTF-8 bytes]
```

Encoding `Note(id="n1", title="Hello", body="World")` field by field:

**`id = "n1"` (tag 1)**
- tag byte: `0x0a`
- length: `0x02` (2 bytes)
- value: `0x6e 0x31` ("n" and "1" in ASCII)
- wire: `0a 02 6e 31`

**`title = "Hello"` (tag 2)**
- tag byte: `0x12`
- length: `0x05` (5 bytes)
- value: `0x48 0x65 0x6c 0x6c 0x6f`
- wire: `12 05 48 65 6c 6c 6f`

**`body = "World"` (tag 3)**
- tag byte: `0x1a`
- length: `0x05` (5 bytes)
- value: `0x57 0x6f 0x72 0x6c 0x64`
- wire: `1a 05 57 6f 72 6c 64`

Full message — 18 bytes total:

```
0a 02 6e 31  12 05 48 65 6c 6c 6f  1a 05 57 6f 72 6c 64
│  │  └─┘    │  │  └─────────────┘  │  │  └─────────────┘
│  │  "n1"   │  │     "Hello"       │  │     "World"
│  2 bytes   │  5 bytes             │  5 bytes
tag(id)      tag(title)             tag(body)
```

Verify it yourself in the gateway venv:

```python
from gen import notes_pb2

note = notes_pb2.Note(id="n1", title="Hello", body="World")
print(note.SerializeToString().hex())
# 0a026e3112054865 6c6c6f1a05576f72 6c64
```

### Why this design — three key benefits

**1. Unknown fields are skippable.** If a new field `author = 4` is added to `Note` but an old gateway doesn't know about it, the gateway reads the tag byte, sees tag 4 / wire type 2, reads past the length-prefixed value, and continues without crashing. This is why protobuf is backwards-compatible: unknown fields are silently skipped.

**2. Missing fields cost zero bytes.** There is no null placeholder for absent fields. If `body` is an empty string, it simply does not appear in the output. The decoder initialises every field to its zero value and updates only the ones it encounters. Fields can also appear in any order — the tag byte always identifies what you're reading.

**3. It is compact.** The 3-field Note above takes 18 bytes. The equivalent JSON `{"id":"n1","title":"Hello","body":"World"}` is 40 bytes — more than twice the size — and that gap widens with field name length and message nesting.

### How this plays out in the gateway for `GetNote`

```
python-server                              api-gateway
NotesServicer.GetNote()
  note = Note(id="n1", title="Hello", body="World")
  note.SerializeToString()
  → [0a 02 6e 31 12 05 ...]  ──────────►  raw bytes arrive on socket
                                            Note.FromString(raw_bytes)
                                            reads 0x0a → tag 1 / LEN
                                            reads 0x02 → 2 bytes follow
                                            reads "n1" → note.id = "n1"
                                            reads 0x12 → tag 2 / LEN
                                            reads 0x05 → 5 bytes follow
                                            reads "Hello" → note.title = "Hello"
                                            … and so on
                                            → Note(id="n1", title="Hello", ...)
                                            → {"id":"n1","title":"Hello",...}
                                            → JSON HTTP response to React
```

---

## Key concepts summary

| Concept | What it means here |
|---|---|
| **`DESCRIPTOR`** | The entire proto schema embedded as binary bytes in the generated file |
| **Tag numbers** | Field identifiers on the wire — `id=1`, `title=2`, `body=3`. Names are irrelevant after compilation. |
| **`SerializeToString`** | Converts a Python message object → protobuf binary for the wire |
| **`FromString`** | Converts protobuf binary from the wire → Python message object |
| **Method path** | `/notes.NotesService/GetNote` — the HTTP/2 URL that routes to the right handler |
| **`unary_unary`** | One request, one response. The HTTP/2 stream opens, both sides send one frame, stream closes. |
| **`unary_stream`** | One request, many responses. Server keeps the HTTP/2 stream open and sends frames until done. |
| **Stub vs Servicer** | Stub = client side (gateway). Servicer = server side (python-server). Same proto, opposite roles. |
| **Serialiser direction** | Stub serialises requests, deserialises responses. Servicer deserialises requests, serialises responses. |
| **`_registered_method=True`** | Pre-registers the method with the channel for a minor dispatch optimisation |
| **Version guards** | Both files abort at import if library versions mismatch the generation-time versions |
| **Wire type** | Integer 0–5 packed into the bottom 3 bits of the tag byte — tells the decoder how many bytes to read |
| **Tag byte** | `(field_tag << 3) \| wire_type` — encodes both field identity and value type in one byte |
| **LEN (wire type 2)** | Format for strings: `[tag_byte][length varint][raw UTF-8 bytes]` |
| **Field names on the wire** | Absent — only tag numbers travel over the network; names live only in the proto and generated code |
| **Backwards compatibility** | Safe to add new fields (unknown tags are skipped); unsafe to renumber existing tags |
