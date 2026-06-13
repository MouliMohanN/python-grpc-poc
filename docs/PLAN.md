# gRPC POC — Implementation Plan

## Goal

Learn gRPC wiring, proto definitions, code generation, and cross-language interoperability using a minimal but realistic example. Two independent services with different domains are implemented in different languages. A single Python client calls both, proving language-agnostic communication.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Python Client (:50051 + :50052)                            │
│    calls ProductsService (Go) and NotesService (Python)     │
└───────────────┬─────────────────────────┬───────────────────┘
                │ gRPC                    │ gRPC
                ▼                         ▼
┌──────────────────────┐   ┌──────────────────────┐
│  Go Server :50051    │   │  Python Server :50052 │
│  ProductsService     │   │  NotesService         │
└──────┬───────────────┘   └──────┬────────────────┘
       │                          │
       ▼                          ▼
┌─────────────────────────────────────────────────┐
│  Redis :6379 (cache)   Postgres :5432 (persist) │
│  Docker Compose                                  │
└─────────────────────────────────────────────────┘
```

---

## Directory Layout

```
python-grpc-poc/
├── PLAN.md
├── docker-compose.yml
├── scripts/
│   └── gen_proto.sh
├── proto/
│   ├── notes.proto
│   └── products.proto
├── go-server/
│   ├── go.mod
│   ├── main.go
│   ├── server.go
│   └── gen/
├── python-server/
│   ├── requirements.txt
│   ├── main.py
│   ├── server.py
│   └── gen/
└── python-client/
    ├── requirements.txt
    ├── main.py
    └── gen/
```

---

## Proto Definitions

### `proto/notes.proto` — Python server

```protobuf
syntax = "proto3";
package notes;

service NotesService {
  rpc CreateNote  (CreateNoteRequest)  returns (CreateNoteResponse);  // unary
  rpc GetNote     (GetNoteRequest)     returns (Note);                 // unary, Redis cache → Postgres
  rpc StreamNotes (StreamNotesRequest) returns (stream Note);          // server streaming
}

message Note               { string id = 1; string title = 2; string body = 3; }
message CreateNoteRequest  { string title = 1; string body = 2; }
message CreateNoteResponse { string id = 1; }
message GetNoteRequest     { string id = 1; }
message StreamNotesRequest {}
```

### `proto/products.proto` — Go server

```protobuf
syntax = "proto3";
package products;

service ProductsService {
  rpc CreateProduct  (CreateProductRequest)  returns (CreateProductResponse);  // unary
  rpc GetProduct     (GetProductRequest)     returns (Product);                 // unary, Redis cache → Postgres
  rpc StreamProducts (StreamProductsRequest) returns (stream Product);          // server streaming
}

message Product               { string id = 1; string name = 2; string category = 3; double price = 4; }
message CreateProductRequest  { string name = 1; string category = 2; double price = 3; }
message CreateProductResponse { string id = 1; }
message GetProductRequest     { string id = 1; }
message StreamProductsRequest { string category = 1; }  // empty = stream all
```

---

## Services & Ports

| Component     | Language | Port  | Domain   |
|---------------|----------|-------|----------|
| Go server     | Go       | 50051 | Products |
| Python server | Python   | 50052 | Notes    |
| Python client | Python   | —     | both     |
| Postgres      | Docker   | 5432  | shared   |
| Redis         | Docker   | 6379  | shared   |

---

## Implementation Notes

### docker-compose.yml
- `postgres:16-alpine` — single DB, tables: `notes`, `products`
- `redis:7-alpine`
- Servers run locally (not containerised) for easy iteration

### Go server — ProductsService
- Libs: `google.golang.org/grpc`, `lib/pq`, `go-redis/redis/v9`
- `CreateProduct` → INSERT, return UUID
- `GetProduct` → Redis `product:<id>` → miss: SELECT + SET (TTL 60s)
- `StreamProducts` → SELECT (optional category filter), stream each row

### Python server — NotesService
- Libs: `grpcio`, `grpcio-tools`, `psycopg2-binary`, `redis`
- `CreateNote` → INSERT, return UUID
- `GetNote` → Redis `note:<id>` → miss: SELECT + SET (TTL 60s)
- `StreamNotes` → SELECT all, yield each row
- Uses `ThreadPoolExecutor` for concurrency

### Python client
- Libs: `grpcio` + stubs from both protos
- Per server: Create → Get (cache miss) → Get again (cache hit) → Stream all

---

## Code Generation

Run `scripts/gen_proto.sh` after any proto change:

```bash
# Notes stubs — python-server and python-client
python -m grpc_tools.protoc -I proto \
  --python_out=python-server/gen --grpc_python_out=python-server/gen \
  --python_out=python-client/gen --grpc_python_out=python-client/gen \
  proto/notes.proto

# Products stubs — go-server
protoc -I proto \
  --go_out=go-server/gen --go-grpc_out=go-server/gen \
  proto/products.proto

# Products stubs — python-client
python -m grpc_tools.protoc -I proto \
  --python_out=python-client/gen --grpc_python_out=python-client/gen \
  proto/products.proto
```

---

## How to Run

```bash
# 1. Start infrastructure
docker compose up -d

# 2. Start Go server (Products)
cd go-server && go run .

# 3. Start Python server (Notes)
cd python-server && python main.py

# 4. Run client
cd python-client && python main.py
```

### Expected client output

```
=== ProductsService (Go :50051) ===
Created product: <uuid>
GetProduct (miss): Product{name=Widget, category=tools, price=9.99}
GetProduct (hit):  Product{name=Widget, category=tools, price=9.99}
StreamProducts:
  Product{...}
  Product{...}

=== NotesService (Python :50052) ===
Created note: <uuid>
GetNote (miss): Note{title=Hello, body=World}
GetNote (hit):  Note{title=Hello, body=World}
StreamNotes:
  Note{...}
  Note{...}
```
