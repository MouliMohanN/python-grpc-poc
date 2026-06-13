# Deep Dive: gRPC Server Reflection

## What it is

gRPC reflection is a **standard gRPC service** — defined in `grpc/reflection/v1alpha/reflection.proto` by the gRPC team — that any server can register alongside its real services. When enabled, it lets any client ask the server at runtime: "what services do you expose and what do they look like?" The server responds with its own compiled schema bytes — the same `FileDescriptorProto` we covered in the [push-based registration doc](push-based-proto-registration-deep-dive.md) — delivered over the wire on demand instead of pushed on startup.

The relationship to the push-based approach:

- **Push-based (FDS)**: server proactively sends its schema to the gateway on startup
- **Reflection**: gateway asks the server for its schema when it connects to it

Both end up in exactly the same place — a `FileDescriptorProto` loaded into the descriptor pool, dynamic message classes, live gRPC calls with no generated stubs. The path to get there is inverted.

---

## How the reflection protocol works

Reflection exposes a single **bidirectional streaming RPC**:

```protobuf
service ServerReflection {
  rpc ServerReflectionInfo(stream ServerReflectionRequest)
      returns (stream ServerReflectionResponse);
}
```

The client sends requests and the server streams responses back over the same open HTTP/2 stream. Request types:

| Request field | What you are asking |
|---|---|
| `list_services` | "What services do you have?" |
| `file_by_filename` | "Give me the descriptor for `notes.proto`" |
| `file_containing_symbol` | "Give me the descriptor that contains `notes.NotesService`" |
| `all_extension_numbers_of_type` | "What extensions exist for this type?" |

The response to a file request is a `FileDescriptorResponse` — a list of serialised `FileDescriptorProto` bytes, one per `.proto` file including all transitive imports. This is byte-for-byte identical to what `protoc --descriptor_set_out` produces. The gateway receives it and loads it into the descriptor pool — the only difference from push-based is how it arrived.

---

## Enabling reflection — one line per server

### Go server (`go-server/main.go`)

```go
import "google.golang.org/grpc/reflection"

grpcServer := grpc.NewServer()
pb.RegisterProductsServiceServer(grpcServer, srv)
reflection.Register(grpcServer)   // ← one line, done
```

### Python server (`python-server/server.py`)

```python
from grpc_reflection.v1alpha import reflection
from gen import notes_pb2

service_names = [
    notes_pb2.DESCRIPTOR.services_by_name['NotesService'].full_name,
    reflection.SERVICE_NAME,
]
reflection.enable_server_reflection(service_names, server)
```

No `FileDescriptorSet` file to compile, no registration endpoint to call. The server now answers schema queries from any client that connects to it.

---

## Service addresses from environment variables

Reflection tells the gateway *what* a server exposes. It does not tell it *where* the server is. The simplest and most portable answer for service addresses is environment variables — the standard mechanism in Docker Compose, Kubernetes, and any 12-factor app.

### The env var format

```bash
# One variable, comma-separated name=address pairs
GRPC_SERVICES=notes=localhost:50052,products=localhost:50051
```

Add more services by appending to the variable — no gateway code changes needed:

```bash
GRPC_SERVICES=notes=localhost:50052,products=localhost:50051,payments=localhost:50053
```

### In Docker Compose

```yaml
# docker-compose.yml
services:
  api-gateway:
    build: ./api-gateway
    ports:
      - "8000:8000"
    environment:
      GRPC_SERVICES: "notes=python-server:50052,products=go-server:50051"

  python-server:
    build: ./python-server
    ports:
      - "50052:50052"

  go-server:
    build: ./go-server
    ports:
      - "50051:50051"
```

Docker Compose service names (`python-server`, `go-server`) resolve as DNS hostnames on the internal network — no IP addresses needed.

### In Kubernetes

```yaml
# k8s/gateway-deployment.yaml
env:
  - name: GRPC_SERVICES
    value: "notes=notes-service:50052,products=products-service:50051"
```

Or via ConfigMap for easier management:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: gateway-config
data:
  GRPC_SERVICES: "notes=notes-service:50052,products=products-service:50051"
```

---

## How the gateway reads env and uses reflection

On startup the gateway reads `GRPC_SERVICES`, connects to each address, queries reflection to discover the full schema, and builds its routing table — all before it starts accepting HTTP requests.

```python
import os
import grpc.aio
from grpc_reflection.v1alpha import reflection_pb2, reflection_pb2_grpc
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

registered_services: dict = {}


def parse_grpc_services() -> dict[str, str]:
    """
    Parse GRPC_SERVICES=notes=localhost:50052,products=localhost:50051
    into {"notes": "localhost:50052", "products": "localhost:50051"}
    """
    raw = os.environ.get("GRPC_SERVICES", "")
    if not raw:
        raise RuntimeError("GRPC_SERVICES env var is not set")

    services = {}
    for entry in raw.split(","):
        name, _, address = entry.partition("=")
        services[name.strip()] = address.strip()
    return services


async def list_services_via_reflection(channel) -> list[str]:
    """Ask the server what services it exposes."""
    stub = reflection_pb2_grpc.ServerReflectionStub(channel)

    async def requests():
        yield reflection_pb2.ServerReflectionRequest(list_services="")

    service_names = []
    async for response in stub.ServerReflectionInfo(requests()):
        if response.HasField("list_services_response"):
            for svc in response.list_services_response.service:
                # Skip the reflection service itself
                if svc.name != "grpc.reflection.v1alpha.ServerReflection":
                    service_names.append(svc.name)
    return service_names


async def fetch_schema_via_reflection(channel, service_name: str):
    """Fetch the FileDescriptorProto for a service and load it into a pool."""
    stub = reflection_pb2_grpc.ServerReflectionStub(channel)

    async def requests():
        yield reflection_pb2.ServerReflectionRequest(
            file_containing_symbol=service_name
        )

    pool = descriptor_pool.DescriptorPool()
    async for response in stub.ServerReflectionInfo(requests()):
        if response.HasField("file_descriptor_response"):
            for fd_bytes in response.file_descriptor_response.file_descriptor_proto:
                fd_proto = descriptor_pb2.FileDescriptorProto.FromString(fd_bytes)
                pool.Add(fd_proto)

    return pool, message_factory.MessageFactory(pool=pool)


async def bootstrap_services():
    """
    Read GRPC_SERVICES, connect to each server, query reflection,
    populate registered_services. Called once at gateway startup.
    """
    for name, address in parse_grpc_services().items():
        channel = grpc.aio.insecure_channel(address)

        # Step 1: discover what services this server exposes
        grpc_service_names = await list_services_via_reflection(channel)

        # Step 2: load the schema for each discovered service
        pools = {}
        factories = {}
        for grpc_svc in grpc_service_names:
            pool, factory = await fetch_schema_via_reflection(channel, grpc_svc)
            pools[grpc_svc] = pool
            factories[grpc_svc] = factory

        registered_services[name] = {
            "address":   address,
            "channel":   channel,
            "services":  grpc_service_names,   # e.g. ["notes.NotesService"]
            "pools":     pools,
            "factories": factories,
        }
        print(f"[gateway] registered {name} @ {address} → {grpc_service_names}")
```

### Wiring into FastAPI lifespan

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    await bootstrap_services()          # reads env, connects, queries reflection
    yield
    for svc in registered_services.values():
        await svc["channel"].close()

app = FastAPI(lifespan=lifespan)
```

### Making a dynamic call

```python
async def call_rpc(service_alias: str, method_path: str, request_data: dict):
    """
    service_alias: the name from GRPC_SERVICES, e.g. "notes"
    method_path:   full gRPC path, e.g. "notes.NotesService/GetNote"
    """
    svc = registered_services[service_alias]

    # Find which pool owns this method
    package_service, _, method_name = method_path.rpartition("/")
    pool    = svc["pools"][package_service]
    factory = svc["factories"][package_service]

    method_descriptor = pool.FindMethodByName(method_path.replace("/", "."))
    RequestClass  = factory.GetPrototype(method_descriptor.input_type)
    ResponseClass = factory.GetPrototype(method_descriptor.output_type)

    request = RequestClass(**request_data)

    return await svc["channel"].unary_unary(
        f"/{method_path}",
        request_serializer=lambda x: x.SerializeToString(),
        response_deserializer=ResponseClass.FromString,
    )(request)
```

### What the startup log looks like

```
[gateway] registered notes     @ localhost:50052 → ['notes.NotesService']
[gateway] registered products  @ localhost:50051 → ['products.ProductsService']
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

No proto files. No codegen. No generated `_pb2.py`. The gateway discovered everything from the live servers.

---

## Full startup flow

```
Gateway starts
  │
  ├─ reads GRPC_SERVICES from env
  │     notes=localhost:50052
  │     products=localhost:50051
  │
  ├─ for each service:
  │     connect (gRPC channel)
  │       │
  │       ├─ list_services → ["notes.NotesService"]
  │       │
  │       └─ file_containing_symbol("notes.NotesService")
  │             → FileDescriptorProto bytes
  │             → loaded into descriptor pool
  │             → dynamic message classes built
  │
  ├─ all services registered in memory
  │
  └─ FastAPI starts accepting HTTP requests
         ↓
    POST /notes → call_rpc("notes", "notes.NotesService/CreateNote", {...})
    GET /notes/{id} → call_rpc("notes", "notes.NotesService/GetNote", {...})
    GET /products → call_rpc("products", "products.ProductsService/StreamProducts", {...})
```

---

## Schema caching

The reflection query runs once per service at gateway startup. Results live in `registered_services` for the process lifetime — no per-request overhead.

If a service deploys a new schema version, the gateway picks it up on its next restart (which in Kubernetes is a rolling update triggered by the new service deployment). The schema is always consistent with the running server because reflection returns what the live process actually serves.

---

## The tools ecosystem — reflection's biggest practical benefit

Because reflection is a standard protocol, every gRPC tool supports it with zero configuration.

### `grpcurl` — curl for gRPC

```bash
# List all services
grpcurl -plaintext localhost:50051 list
# products.ProductsService

# Describe the full schema
grpcurl -plaintext localhost:50051 describe products.ProductsService
# service ProductsService {
#   rpc CreateProduct ( .products.CreateProductRequest ) returns ( .products.CreateProductResponse );
#   rpc GetProduct    ( .products.GetProductRequest )    returns ( .products.Product );
#   rpc StreamProducts( .products.StreamProductsRequest) returns ( stream .products.Product );
# }

# Make a unary call
grpcurl -plaintext \
  -d '{"name":"Widget","category":"tools","price":9.99}' \
  localhost:50051 products.ProductsService/CreateProduct
# { "id": "f3a9c1b2-4e5d-..." }

# Get by ID
grpcurl -plaintext \
  -d '{"id":"f3a9c1b2-4e5d-..."}' \
  localhost:50051 products.ProductsService/GetProduct
# { "id": "f3a9c1b2-...", "name": "Widget", "category": "tools", "price": 9.99 }

# Server streaming
grpcurl -plaintext \
  -d '{"category":"tools"}' \
  localhost:50051 products.ProductsService/StreamProducts
# { "id": "...", "name": "Widget", "category": "tools", "price": 9.99 }
# { "id": "...", "name": "Hammer", "category": "tools", "price": 4.99 }
```

### `grpcui` — browser-based UI, zero setup

```bash
grpcui -plaintext localhost:50051
# Serving gRPC UI on http://127.0.0.1:58080
```

Opens a full web UI with all services and methods auto-populated. Click a method, fill in a form, send the request, see the response. No proto files, no Postman collection.

### Postman

Add a gRPC request, enter the server address, click "Use Server Reflection" — all services and methods appear immediately.

### Evans — interactive gRPC REPL

```bash
evans --reflection --port 50052 repl

notes.NotesService@127.0.0.1:50052> call CreateNote
title (TYPE_STRING) => Hello
body (TYPE_STRING) => World
{
  "id": "abc-123"
}
```

None of these tools need the `.proto` file. Enabling reflection is worth doing on every server just for the tooling benefit, independent of whether you use it in the gateway.

---

## Security — the critical production consideration

Reflection exposes your entire API schema to anyone who can reach the server's port. In a private internal network this is usually acceptable. On a public endpoint it is not.

### Common production pattern

```
Development / staging     → reflection ON   (engineers use grpcurl freely)
Production internal mesh  → reflection ON   (controlled network, internal tools only)
Production public-facing  → reflection OFF  (schema is a security boundary)
```

Disabling is a matter of not registering it:

```go
// Go — simply do not call reflection.Register(grpcServer)
```

```python
# Python — simply do not call enable_server_reflection()
```

For environment-controlled toggling:

```go
if os.Getenv("GRPC_REFLECTION_ENABLED") == "true" {
    reflection.Register(grpcServer)
}
```

```python
if os.environ.get("GRPC_REFLECTION_ENABLED") == "true":
    reflection.enable_server_reflection(service_names, server)
```

---

## Reflection vs push-based FDS — side by side

| | Push-based FDS | gRPC Reflection + env |
|---|---|---|
| **Who initiates schema transfer** | Server pushes to gateway on startup | Gateway pulls from server on connect |
| **Service address config** | Consul / etcd | Environment variable |
| **Schema freshness** | As fresh as the last push | Always current — queried live from running server |
| **FDS file in server image** | Required | Not required |
| **Registration endpoint on gateway** | Required | Not required |
| **Server-side change to enable** | Compile FDS + add startup call | One line |
| **Works if server is offline at gateway start** | Yes — FDS already in registry | No — requires live connection |
| **Schema auditable / version-controlled** | Yes — stored with timestamp | No — ephemeral, fetched live |
| **Tooling ecosystem** | None | `grpcurl`, `grpcui`, Postman, Evans |
| **Security** | Schema only reaches gateway | Schema reachable by any network client |
| **Infrastructure dependencies** | Consul / etcd cluster | None beyond the gRPC servers themselves |

---

## Which approach to use when

| Situation | Recommendation |
|---|---|
| Developer tooling and debugging | Reflection — enable it on all servers, use `grpcurl` and `grpcui` freely |
| Public-facing gRPC endpoint | No reflection — schema is a security boundary |
| POC / small internal project | **Reflection + env vars** — zero infrastructure, zero proto file management |
| Production internal mesh, schema rarely changes | Reflection + env vars or Kubernetes service DNS |
| Schema must be auditable and version-controlled | Push FDS — schema stored in registry with full history |
| Gateway must start before upstream servers | Push FDS — reflection requires a live server to query |
| Cross-team contract management at scale | Buf BSR — teams publish and consume versioned modules |

---

## Key concepts summary

| Concept | What it means |
|---|---|
| **gRPC reflection** | Standard gRPC service that exposes the server's schema over the wire at runtime |
| **`ServerReflectionInfo`** | Bidirectional streaming RPC — client sends what it wants to know, server streams back schema bytes |
| **`list_services`** | Reflection request that returns all service names the server exposes — gateway uses this to auto-discover what is available |
| **`file_containing_symbol`** | Reflection request that returns the full `FileDescriptorProto` for a named service — gateway uses this to build the descriptor pool |
| **`FileDescriptorProto`** | Compiled binary representation of one `.proto` file — what reflection returns and what the descriptor pool accepts |
| **Descriptor pool** | In-memory registry of all known protobuf types — loaded from reflection response at startup, no generated `_pb2.py` files needed |
| **`GRPC_SERVICES` env var** | `name=address` pairs that tell the gateway which servers to connect to — replaces service discovery infrastructure |
| **Bootstrap on startup** | Gateway reads env, connects to each server, queries reflection, builds routing table — all before accepting requests |
| **Schema cache** | Descriptor pool built once at startup per service — no per-request reflection overhead |
| **Security trade-off** | Reflection makes schema discoverable by any network client — disable on public-facing servers via env toggle |
| **`grpcurl` / `grpcui`** | Tools that use reflection to call gRPC servers from terminal or browser without any proto files |
