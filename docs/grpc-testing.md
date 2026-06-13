# Testing gRPC Services with grpcurl and grpcui

Both tools talk directly to the gRPC servers — bypassing the REST gateway and the React frontend entirely. No `.proto` files needed; they use reflection to discover the schema live from the running server.

---

## Prerequisites

```bash
brew install grpcurl
brew install grpcui
```

Both servers must be running with reflection enabled:

```bash
# Terminal 1 — Python server (NotesService :50052)
cd python-server && .venv/bin/python server.py

# Terminal 2 — Go server (ProductsService :50051)
cd go-server && go run .
```

---

## Verify reflection is working

```bash
grpcurl -plaintext localhost:50052 list   # NotesService
grpcurl -plaintext localhost:50051 list   # ProductsService
```

Expected output:

```
notes.NotesService
grpc.reflection.v1alpha.ServerReflection
```

```
products.ProductsService
grpc.reflection.v1alpha.ServerReflection
```

If you get `Failed to dial target host` — the server is not running. If you get `server does not support the reflection API` — reflection is not registered (check the setup steps).

---

## NotesService — grpcurl

### CreateNote

```bash
grpcurl -plaintext \
  -d '{"title": "hello", "body": "world"}' \
  localhost:50052 notes.NotesService/CreateNote
```

Response:

```json
{ "id": "f3a9c1b2-4e5d-4f6a-8b3c-1d2e3f4a5b6c" }
```

### GetNote

```bash
grpcurl -plaintext \
  -d '{"id": "f3a9c1b2-4e5d-4f6a-8b3c-1d2e3f4a5b6c"}' \
  localhost:50052 notes.NotesService/GetNote
```

Response:

```json
{ "id": "f3a9c1b2-...", "title": "hello", "body": "world" }
```

Check the python-server terminal — first call logs `cache MISS`, second call logs `cache HIT`.

### StreamNotes

`StreamNotesRequest` has no fields — pass an empty object:

```bash
grpcurl -plaintext \
  -d '{}' \
  localhost:50052 notes.NotesService/StreamNotes
```

Each note arrives as a separate JSON object on its own line as the server streams them:

```json
{ "id": "f3a9c1b2-...", "title": "hello", "body": "world" }
{ "id": "a1b2c3d4-...", "title": "second", "body": "note" }
```

---

## ProductsService — grpcurl

### CreateProduct

```bash
grpcurl -plaintext \
  -d '{"name": "Widget", "category": "tools", "price": 9.99}' \
  localhost:50051 products.ProductsService/CreateProduct
```

Response:

```json
{ "id": "a1b2c3d4-4e5d-4f6a-8b3c-1d2e3f4a5b6c" }
```

### GetProduct

```bash
grpcurl -plaintext \
  -d '{"id": "a1b2c3d4-4e5d-4f6a-8b3c-1d2e3f4a5b6c"}' \
  localhost:50051 products.ProductsService/GetProduct
```

Response:

```json
{ "id": "a1b2c3d4-...", "name": "Widget", "category": "tools", "price": 9.99 }
```

### StreamProducts

Stream all products:

```bash
grpcurl -plaintext \
  -d '{}' \
  localhost:50051 products.ProductsService/StreamProducts
```

Stream filtered by category:

```bash
grpcurl -plaintext \
  -d '{"category": "tools"}' \
  localhost:50051 products.ProductsService/StreamProducts
```

Each product streams back as a separate JSON line.

---

## Describing the schema

Useful when you want to see the exact field names and types before constructing a request:

```bash
# Describe a service
grpcurl -plaintext localhost:50052 describe notes.NotesService

# Describe a specific message
grpcurl -plaintext localhost:50052 describe notes.Note
grpcurl -plaintext localhost:50052 describe notes.CreateNoteRequest

# Describe all types in the package
grpcurl -plaintext localhost:50051 describe products
```

---

## NotesService — grpcui

```bash
grpcui -plaintext localhost:50052
# → Serving gRPC UI on http://127.0.0.1:<port>
```

The browser opens automatically. Walkthrough:

1. **Service** dropdown — select `notes.NotesService`
2. **Method** dropdown — select the RPC you want to call
3. Fill in the request fields in the form (grpcui builds the form from the schema)
4. Click **Invoke**

For `StreamNotes`: leave the request form empty (no fields), click **Invoke** — streamed responses appear as a list as they arrive.

---

## ProductsService — grpcui

```bash
grpcui -plaintext localhost:50051
```

Same walkthrough as above. For `StreamProducts`, the `category` field is optional — leave it blank to stream all products, or fill it in to filter.

---

## Quick reference

| RPC | Server | Empty body? | Filter field |
|---|---|---|---|
| `CreateNote` | `:50052` | No — title + body required | — |
| `GetNote` | `:50052` | No — id required | — |
| `StreamNotes` | `:50052` | Yes — `{}` | — |
| `CreateProduct` | `:50051` | No — name + category + price required | — |
| `GetProduct` | `:50051` | No — id required | — |
| `StreamProducts` | `:50051` | Yes — `{}` streams all | `category` (optional) |
