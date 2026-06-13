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
- [gRPC clients deep dive](docs/grpc-clients-deep-dive.md) — how channels, stubs, and async wiring work in the API gateway
- [Generated notes stubs deep dive](docs/generated-notes-stubs-deep-dive.md) — what `notes_pb2.py` and `notes_pb2_grpc.py` actually do, line by line
- [gen_proto.sh deep dive](docs/gen-proto-script-deep-dive.md) — how the code generation script works, flag by flag
- [Schema registry deep dive](docs/schema-registry-deep-dive.md) — why registries exist, how Buf works, breaking change rules, and how this project would look with BSR
