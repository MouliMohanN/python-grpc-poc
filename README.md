# python-grpc-poc

A full-stack gRPC proof of concept demonstrating cross-language service communication and REST-to-gRPC bridging.

```
React :5173  →  FastAPI gateway :8000  →  Go server :50051  (ProductsService)
                                        →  Python server :50052  (NotesService)
                                               ↓
                                        Postgres + Redis
```

## Services

| Directory | Language | Role |
|-----------|----------|------|
| `go-server/` | Go | gRPC server — ProductsService |
| `python-server/` | Python | gRPC server — NotesService |
| `api-gateway/` | Python / FastAPI | REST server + gRPC client |
| `frontend/` | React + TypeScript | Dashboard UI |
| `proto/` | Protobuf | Shared service contracts |

## Docs

- [Setup guide](docs/setup.md) — prerequisites, venv setup, proto generation, running all services
