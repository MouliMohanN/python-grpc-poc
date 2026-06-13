# Setup Guide

Step-by-step instructions to get the full stack running locally.

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Docker + Docker Compose | 24+ | [docker.com](https://www.docker.com/) |
| Go | 1.22+ | [go.dev](https://go.dev/dl/) |
| Python | 3.12 | `brew install python@3.12` |
| Node.js | 18+ | [nodejs.org](https://nodejs.org/) |
| protoc | any recent | `brew install protobuf` |
| protoc-gen-go | latest | `go install google.golang.org/protobuf/cmd/protoc-gen-go@latest` |
| protoc-gen-go-grpc | latest | `go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@latest` |

---

## 1. Clone the repo

```bash
git clone <repo-url>
cd python-grpc-poc
```

---

## 2. Start infrastructure (Postgres + Redis)

```bash
docker compose up -d
```

This starts:
- **Postgres 16** on `localhost:5432` (DB: `grpcpoc`, user/password: `grpc`)
- **Redis 7** on `localhost:6379`

The `scripts/init.sql` file is automatically run on first start and creates the `notes` and `products` tables.

Verify both are healthy:

```bash
docker compose ps
```

---

## 3. Set up Python virtual environments

Each Python service manages its own isolated environment.

**python-server** (Notes gRPC service):

```bash
cd python-server
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cd ..
```

**api-gateway** (FastAPI REST gateway):

```bash
cd api-gateway
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cd ..
```

---

## 4. Generate proto stubs

Run once after any `.proto` file change. Requires `protoc`, `protoc-gen-go`, `protoc-gen-go-grpc`, and the `api-gateway` venv to be set up (step 3).

```bash
bash scripts/gen_proto.sh
```

This generates:
- `go-server/gen/` — Go stubs for `ProductsService`
- `python-server/gen/` — Python stubs for `NotesService`
- `api-gateway/gen/` — Python stubs for both services (used as gRPC client)

---

## 5. Install Go dependencies

```bash
cd go-server
go mod tidy
cd ..
```

---

## 6. Install frontend dependencies

```bash
cd frontend
npm install
cd ..
```

---

## Running the stack

Open four terminal tabs/panes and run each service:

### Tab 1 — Go server (ProductsService, `:50051`)

```bash
cd go-server
go run .
```

Expected output:
```
Connected to Postgres and Redis
ProductsService listening on :50051
```

### Tab 2 — Python gRPC server (NotesService, `:50052`)

```bash
cd python-server
.venv/bin/python main.py
```

Expected output:
```
Connected to Postgres and Redis
NotesService listening on :50052
```

### Tab 3 — FastAPI gateway (`:8000`)

```bash
cd api-gateway
.venv/bin/uvicorn main:app --port 8000 --reload
```

Expected output:
```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

Auto-generated REST docs available at `http://localhost:8000/docs`.

### Tab 4 — React frontend (`:5173`)

```bash
cd frontend
npm run dev
```

Open `http://localhost:5173` in your browser.

---

## Architecture recap

```
React :5173
  └─ REST (HTTP/JSON)
       └─ FastAPI gateway :8000
            ├─ gRPC → Go server :50051  (ProductsService)
            │            └─ Postgres + Redis
            └─ gRPC → Python server :50052  (NotesService)
                         └─ Postgres + Redis
```

---

## Regenerating proto stubs

If you edit `proto/notes.proto` or `proto/products.proto`, re-run:

```bash
bash scripts/gen_proto.sh
```

Then restart the affected services.

---

## Stopping everything

```bash
docker compose down        # stop Postgres + Redis
# Ctrl-C each terminal tab for the other services
```

To also wipe the Postgres volume:

```bash
docker compose down -v
```
