# Deep Dive: Push-Based Proto Registration at Scale

## The core idea

Instead of the gateway pulling proto files from upstream servers, servers push their own contract to the gateway when they start up. The gateway receives the contract and immediately knows how to call that server — no manual file copying, no `gen_proto.sh`, no coordinated deployment.

```
Notes server starts
  → pushes its contract to the gateway
  → gateway registers it
  → gateway can now route /notes/* to it

Products server starts
  → pushes its contract to the gateway
  → gateway registers it
  → gateway can now route /products/* to it
```

This is the right intuition. Servers are the source of truth for their own contract, so they should push it rather than waiting for someone to pull it. Apollo Federation (GraphQL) uses exactly this model in production. The implementation details are where the naive approach breaks down at scale.

---

## Why the naive implementation fails at scale

### The naive approach

```
POST /register-proto
  → save .proto text file to disk
  → run protoc to generate _pb2.py files
  → append entry to registrations.json
  → restart gateway to pick up new stubs
```

### Problem 1: Three separate concerns mixed into one endpoint

The registration endpoint conflates concerns that have different change rates and different failure modes:

| Concern | Question | Change rate |
|---|---|---|
| **Service discovery** | Where is service X? Is it healthy? | Every deployment (minutes) |
| **Contract management** | What does service X expose? | Schema changes (days/weeks) |
| **Dynamic routing** | How do I forward a REST call to the right gRPC upstream? | Driven by the above two |

A service that redeploys to a new IP should not need to re-push its proto. A service that changes its schema should not need to re-register its address. Mixing them means any change touches everything.

### Problem 2: `registrations.json` cannot exist in production

The moment you run more than one gateway instance — and you always run more than one for availability — `registrations.json` on each instance's local disk diverges immediately.

```
Load balancer
  ├── Gateway instance A  (registered notes.proto ✓)
  ├── Gateway instance B  (never received it      ✗)
  └── Gateway instance C  (never received it      ✗)
```

Two thirds of requests fail. There is no fix for this with a local file. You need an external store that all instances read from.

### Problem 3: Running `protoc` at runtime inside a production process

Modern production containers are treated as **immutable**. You build an image, test it, deploy it. Kubernetes best practice is a read-only root filesystem. Writing `.proto` files and running `protoc` inside a running container violates this:

- `protoc` must be installed in the production image, bloating it
- File writes during live traffic create a window of inconsistency
- If `protoc` fails halfway (malformed proto, disk full, permissions error), the gateway is in a partially-updated state
- Multiple gateway instances running `protoc` simultaneously on the same proto is a race condition

### Problem 4: Python modules cannot be safely hot-reloaded

Python's import system caches modules in `sys.modules`. If `notes_pb2.py` is regenerated on disk while the process is running, the running process still uses the old in-memory version. Options:

- **`importlib.reload()`** — dangerous: existing in-memory references still point at the old class
- **Process restart** — safe but causes downtime and drops active connections
- **Dynamic imports per request** — architecturally non-trivial, not what normal FastAPI does

There is no clean path to hot-reloading generated stubs without restarting.

### Problem 5: Security surface

You are accepting a file from a network request, writing it to disk, and executing a subprocess against it:

- A malicious server could push a `notes.proto` that overwrites the real one with different tag numbers — silently corrupting all Note reads for every client
- `protoc` on a crafted proto could behave unexpectedly
- Without mutual TLS on the endpoint, any caller can register anything

All solvable, but each fix adds complexity to what looks like a simple endpoint.

---

## The production-grade decomposition

Production systems separate the three concerns into two registries:

```
┌──────────────────────────────────────────────────────────────┐
│  Service Registry  (etcd / Consul)                           │
│  Answers: where is service X? is it healthy?                 │
│  Updated by: services on startup via sidecar / SDK           │
│  Read by: gateway watches for changes                        │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  Schema Registry  (Buf BSR / proto monorepo / compiled FDS)  │
│  Answers: what does service X expose?                        │
│  Updated by: CI/CD on proto merge, or server on startup      │
│  Read by: gateway loads descriptor at runtime                │
└──────────────────────────────────────────────────────────────┘
```

These are separate because their change rates and failure modes differ. In the push-based model, the server can push **both** on startup — but into the right stores.

---

## The key insight: `FileDescriptorSet` instead of `.proto` + `protoc`

You do not need to send a `.proto` text file and run `protoc` on it at runtime. `protoc` produces a **compiled binary descriptor** called a `FileDescriptorSet` — this is the actual internal representation of the schema. You can send this binary directly and load it into the runtime descriptor pool with zero file I/O and zero subprocess execution.

### Producing the descriptor (done once at build time, in CI)

```bash
# Compile the proto to a binary FileDescriptorSet
protoc --descriptor_set_out=notes.fds --include_imports proto/notes.proto

# Or with buf
buf build -o notes.fds
```

This `.fds` file is a binary blob that embeds the entire schema. It is produced once in CI and bundled with the server. The server carries its own compiled descriptor.

### What the server pushes on startup

```json
{
  "name": "notes",
  "address": "10.0.1.5:50052",
  "descriptor": "<base64-encoded contents of notes.fds>"
}
```

No `.proto` text. No `protoc` on the gateway side. The descriptor IS the compiled contract.

### What the gateway does with it (pure in-memory, no restart)

```python
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
import base64, grpc

registered_services = {}

def register_service(name: str, address: str, descriptor_b64: str):
    descriptor_bytes = base64.b64decode(descriptor_b64)

    # Load binary descriptor into the pool — pure in-memory, no files, no subprocess
    fds = descriptor_pb2.FileDescriptorSet.FromString(descriptor_bytes)
    pool = descriptor_pool.DescriptorPool()
    for file_proto in fds.file:
        pool.Add(file_proto)

    # Build dynamic message classes — no generated _pb2.py files needed at all
    factory = message_factory.MessageFactory(pool=pool)

    # Create gRPC channel to the server
    channel = grpc.aio.insecure_channel(address)

    # Register in memory — immediately callable, no restart
    registered_services[name] = {
        "pool": pool,
        "factory": factory,
        "channel": channel,
        "address": address,
    }

# Making a dynamic gRPC call — no stub, no generated code
async def call_service(service_name: str, method_path: str, request_data: dict):
    svc = registered_services[service_name]

    method_descriptor = svc["pool"].FindMethodByName(method_path)
    RequestClass  = svc["factory"].GetPrototype(method_descriptor.input_type)
    ResponseClass = svc["factory"].GetPrototype(method_descriptor.output_type)

    request = RequestClass(**request_data)

    response = await svc["channel"].unary_unary(
        f"/{method_path}",
        request_serializer=lambda x: x.SerializeToString(),
        response_deserializer=ResponseClass.FromString,
    )(request)

    return response
```

No `protoc`, no `gen_proto.sh`, no `_pb2.py` files on disk, no process restart. The descriptor pool is the runtime equivalent of generated stubs.

---

## Replace `registrations.json` with Consul or etcd

### What `registrations.json` is trying to do

```json
{
  "services": [
    {
      "name": "notes",
      "address": "10.0.1.5:50052",
      "descriptor": "<base64 fds>",
      "registered_at": "2026-06-13T10:30:00Z",
      "version": "1.2.0"
    }
  ]
}
```

It persists service registrations so the gateway can reconstruct its state after a restart. The concept is right. The implementation — a local file — cannot scale.

### What it needs to be: a distributed KV store with watch semantics

| Property | `registrations.json` | etcd / Consul |
|---|---|---|
| Distributed | No — local disk per instance | Yes — shared by all gateway instances |
| Consistency | None across instances | Strong (etcd) / eventual (Consul) |
| Change notification | None — requires restart or polling | Watch API — push notification on any change |
| Health checking | None — dead services stay registered forever | Built-in TTL — dead services auto-deregister |
| Scale | One gateway instance | Unlimited instances, all identical state |
| Failure | Gateway restart loses state | HA cluster, survives node failures |

### How it works with Consul

**Server side — registers itself on startup:**

```python
import consul, base64, json

def register_with_consul(service_name, grpc_address, fds_path):
    client = consul.Consul()

    with open(fds_path, 'rb') as f:
        descriptor_b64 = base64.b64encode(f.read()).decode()

    client.kv.put(f"services/{service_name}", json.dumps({
        "name": service_name,
        "address": grpc_address,
        "descriptor": descriptor_b64,
        "version": "1.2.0",
    }))

    # Register health check — Consul auto-deregisters if TTL lapses
    client.agent.service.register(
        service_name,
        check=consul.Check.ttl("30s"),
    )

# Called on startup
register_with_consul("notes", "10.0.1.5:50052", "notes.fds")

# Called every ~15s to keep TTL alive
client.agent.check.ttl_pass(f"service:{service_name}")
```

**Gateway side — watches for changes, updates in memory:**

```python
import consul.aio, asyncio, json

async def watch_services():
    client = consul.aio.Consul()
    index = None

    while True:
        # Long-polls Consul — blocks until something changes
        index, services = await client.kv.get(
            'services/', index=index, recurse=True
        )
        if not services:
            continue

        for entry in services:
            data = json.loads(entry['Value'])
            register_service(
                data['name'],
                data['address'],
                data['descriptor'],
            )
            # New service is immediately callable — no restart, no file writes
```

All gateway instances watch the same Consul cluster. A new instance starting cold reads Consul and is immediately fully configured. A dead server's TTL lapses and its entry is removed — the gateway stops routing to it automatically.

---

## Full production architecture

```
┌─────────────────┐  on startup   ┌──────────────────────────────┐
│  Notes server   │ ────────────► │  Consul cluster              │
│                 │  PUT          │                              │
│  carries its    │  services/    │  - distributed KV            │
│  own compiled   │  notes        │  - TTL health checking       │
│  notes.fds      │  { addr, fds }│  - watch / long-poll API     │
└─────────────────┘               └──────────────┬───────────────┘
                                                  │
┌─────────────────┐  on startup                  │ watch (all instances)
│  Products server│ ────────────►                │ push on any change
│                 │  PUT                         │
│  carries its    │  services/                   ▼
│  own products   │  products    ┌──────────────────────────────┐
│  .fds           │  { addr, fds}│  Gateway  A  B  C            │
└─────────────────┘              │                              │
                                 │  - descriptor pool (memory)  │
                                 │  - dynamic message factory   │
                                 │  - gRPC channels per service │
                                 │  - routes mounted dynamically│
                                 │                              │
                                 │  all instances identical     │
                                 │  new instance: read Consul   │
                                 │  dead service: TTL removes   │
                                 └──────────────────────────────┘
```

**What happens when Notes server redeploys to a new IP:**

```
Notes server (new pod, 10.0.1.6:50052) starts
  → registers in Consul: services/notes { address: 10.0.1.6:50052, ... }
  → Consul pushes change to all gateway instances
  → each gateway: closes old channel to 10.0.1.5, opens new one to 10.0.1.6
  → traffic automatically routes to new address
  → no gateway restart, no human intervention
```

**What happens when Notes server dies unexpectedly:**

```
Notes server stops sending TTL heartbeats
  → Consul marks it unhealthy after 30s
  → gateway watch fires
  → gateway removes notes from registered_services
  → /notes/* routes return 503 until server recovers
  → when server recovers, it re-registers and gateway picks it up
```

**What happens when Notes server updates its schema:**

```
Notes server (new version, new notes.fds with author field added)
  → registers with new descriptor in Consul
  → gateway watch fires
  → gateway reloads descriptor pool for notes service
  → new `author` field now available in responses
  → no restart, no codegen, no file I/O
```

---

## Comparison: naive approach vs production approach

| | Naive (file + protoc + JSON) | Production (FDS + Consul) |
|---|---|---|
| **Contract format** | `.proto` text file | Compiled `FileDescriptorSet` binary |
| **Codegen at runtime** | Yes — runs `protoc` on every registration | No — descriptor pool loaded in memory |
| **Persistence** | `registrations.json` on local disk | Consul / etcd cluster |
| **Multi-instance** | Broken — each instance diverges | Works — all instances watch same Consul |
| **Health checking** | None — dead services stay registered | Built-in — TTL auto-deregisters dead services |
| **Change notification** | None — requires restart | Watch API — immediate push to all instances |
| **Restart to activate** | Yes — required | No — hot-loaded into descriptor pool |
| **Container immutability** | Violated — writes to filesystem | Preserved — pure in-memory operations |
| **Security surface** | Accepting files + executing subprocess | Accepting binary blob + loading into pool |
| **`protoc` in prod image** | Required | Not required |

---

## When the naive approach is acceptable

The naive approach (file + protoc + registrations.json) is acceptable when:

- **Single gateway instance** — no multi-instance divergence problem
- **Restart is acceptable** — low-traffic internal tool, or blue/green deployment handles it
- **Controlled environment** — you own all the servers, no hostile inputs
- **Learning / POC** — understanding the concept before implementing the production version

The production approach becomes necessary when:

- **Multiple gateway instances** — horizontal scaling, high availability
- **Zero-downtime requirement** — restarts are not acceptable
- **Many upstream services** — managing N proto files manually is unsustainable
- **Multiple teams** — you cannot trust all registration sources equally

---

## Key concepts summary

| Concept | What it means |
|---|---|
| **Push-based registration** | Servers push their contract to the gateway on startup rather than the gateway pulling it |
| **`FileDescriptorSet` (FDS)** | Pre-compiled binary representation of a `.proto` schema — produced by `protoc --descriptor_set_out`, loaded into Python's descriptor pool at runtime with no subprocess |
| **Descriptor pool** | Python's in-memory registry of all known protobuf message types — the runtime equivalent of generated `_pb2.py` files |
| **Dynamic message factory** | Creates Python message classes at runtime from a descriptor pool — no generated code needed |
| **Consul / etcd** | Distributed KV store with watch semantics and TTL health checking — replaces `registrations.json` for all-instance consistency |
| **Watch semantics** | Long-poll API that blocks until a key changes — gateway gets instant push notification when any service registers, deregisters, or updates |
| **TTL health check** | Server sends a heartbeat every N seconds; if it stops, Consul auto-removes it — dead services do not stay registered |
| **Container immutability** | Production containers have read-only filesystems — runtime file writes are an anti-pattern |
| **Split-brain** | When multiple gateway instances have inconsistent state — the core failure mode of `registrations.json` at scale |
