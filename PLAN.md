# gRPC POC — Full Stack Plan

## Goal

Learn gRPC wiring, proto definitions, code generation, and cross-language interoperability. A React frontend talks REST to a Python FastAPI gateway, which is a gRPC client to two backend gRPC servers (Go = Products, Python = Notes). Redis caches reads; Postgres persists data.

---

## Full Architecture

```
┌─────────────────────────────────┐
│  React Frontend  :5173          │
│  (Vite + React)                 │
│  - Notes section (create/get/list)
│  - Products section (create/get/list)
└────────────┬────────────────────┘
             │ REST (HTTP/JSON)
             ▼
┌─────────────────────────────────┐
│  Python API Gateway  :8000      │
│  FastAPI                        │
│  REST server + gRPC client      │
└────────┬───────────────┬────────┘
         │ gRPC          │ gRPC
         ▼               ▼
┌──────────────┐  ┌──────────────┐
│  Go Server   │  │ Python Server│
│  :50051      │  │  :50052      │
│  Products    │  │  Notes       │
└──────┬───────┘  └──────┬───────┘
       │                 │
       ▼                 ▼
┌─────────────────────────────────┐
│  Postgres :5432   Redis :6379   │
│  (Docker Compose)               │
└─────────────────────────────────┘
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
├── go-server/               # gRPC server — ProductsService
│   ├── go.mod
│   ├── main.go
│   ├── server.go
│   └── gen/
├── python-server/           # gRPC server — NotesService
│   ├── requirements.txt
│   ├── main.py
│   ├── server.py
│   └── gen/
├── api-gateway/             # FastAPI — REST ↔ gRPC bridge
│   ├── requirements.txt
│   ├── main.py
│   ├── grpc_clients.py
│   └── gen/
└── frontend/                # React — Vite
    ├── package.json
    ├── vite.config.ts
    └── src/
        ├── App.tsx
        ├── components/
        │   ├── NotesSection.tsx
        │   └── ProductsSection.tsx
        └── api.ts
```

---

## Proto Definitions

### `proto/notes.proto` — Python gRPC server

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

### `proto/products.proto` — Go gRPC server

```protobuf
syntax = "proto3";
package products;

service ProductsService {
  rpc CreateProduct  (CreateProductRequest)  returns (CreateProductResponse);
  rpc GetProduct     (GetProductRequest)     returns (Product);
  rpc StreamProducts (StreamProductsRequest) returns (stream Product);
}

message Product               { string id = 1; string name = 2; string category = 3; double price = 4; }
message CreateProductRequest  { string name = 1; string category = 2; double price = 3; }
message CreateProductResponse { string id = 1; }
message GetProductRequest     { string id = 1; }
message StreamProductsRequest { string category = 1; }
```

---

## Services & Ports

| Component      | Language | Port  | Domain   | Role                      |
|----------------|----------|-------|----------|---------------------------|
| React frontend | TS/React | 5173  | both     | UI                        |
| API gateway    | Python   | 8000  | both     | REST server + gRPC client |
| Go server      | Go       | 50051 | Products | gRPC server               |
| Python server  | Python   | 50052 | Notes    | gRPC server               |
| Postgres       | Docker   | 5432  | shared   | persistence               |
| Redis          | Docker   | 6379  | shared   | cache                     |

---

## REST API (FastAPI Gateway)

| Method | Path             | gRPC call             |
|--------|------------------|-----------------------|
| POST   | `/notes`         | NotesService.CreateNote    |
| GET    | `/notes/{id}`    | NotesService.GetNote       |
| GET    | `/notes`         | NotesService.StreamNotes   |
| POST   | `/products`      | ProductsService.CreateProduct |
| GET    | `/products/{id}` | ProductsService.GetProduct    |
| GET    | `/products`      | ProductsService.StreamProducts|

Uses `grpcio-aio` so FastAPI stays fully async end-to-end.
StreamNotes/StreamProducts consumed fully server-side, returned as JSON array.

---

## Code Generation (`scripts/gen_proto.sh`)

```bash
# Notes stubs — python-server + api-gateway
python -m grpc_tools.protoc -I proto \
  --python_out=python-server/gen --grpc_python_out=python-server/gen \
  --python_out=api-gateway/gen   --grpc_python_out=api-gateway/gen \
  proto/notes.proto

# Products stubs — go-server
protoc -I proto \
  --go_out=go-server/gen --go-grpc_out=go-server/gen \
  proto/products.proto

# Products stubs — api-gateway
python -m grpc_tools.protoc -I proto \
  --python_out=api-gateway/gen --grpc_python_out=api-gateway/gen \
  proto/products.proto
```

---

## How to Run

```bash
# 1. Infrastructure
docker compose up -d

# 2. Go server (Products — :50051)
cd go-server && go run .

# 3. Python gRPC server (Notes — :50052)
cd python-server && python main.py

# 4. API gateway (REST — :8000)
cd api-gateway && uvicorn main:app --port 8000 --reload

# 5. React frontend (:5173)
cd frontend && npm install && npm run dev
```

Open `http://localhost:5173`.

---

## Verification

1. Create a note in the UI → ID returned
2. Fetch note by ID → body shown (python-server logs cache miss)
3. Fetch same ID again → python-server logs cache hit
4. List all notes → list renders
5. Repeat for Products via Go server
