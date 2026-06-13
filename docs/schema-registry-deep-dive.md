# Deep Dive: Proto Schema Registries

## The problem — why copy-pasting `.proto` files breaks at scale

In this project there are two services and one gateway — small enough to share `.proto` files directly. But imagine 50 microservices across 12 teams. Team A owns `notes.proto` and makes a change. Teams B, C, D, E all consume it. How does each team know:

- That a change happened?
- Whether the change breaks their existing client?
- Which version of the proto they are currently running against?
- Whether the tag numbers they depend on are still valid?

Copy-pasting `.proto` files by hand breaks down completely at this scale. You get **proto drift** — each team's copy quietly diverges, and the only way you find out is when a field silently returns the wrong data in production. A schema registry solves this: it is a **central, versioned store for `.proto` files** with built-in compatibility enforcement.

---

## The two main approaches

### Approach A — Buf Schema Registry (BSR)

[Buf](https://buf.build) is the dominant tool in the protobuf ecosystem. It has two parts:

- **`buf` CLI** — a replacement for `protoc` that adds linting, breaking change detection, and dependency management. **Fully free and open source** — you can use it locally and in CI without ever touching the registry.
- **Buf Schema Registry (BSR)** — a hosted registry at `buf.build` where you publish versioned proto modules

#### BSR pricing (as of June 2026)

| Tier | Cost | Private repos | Key limits |
|---|---|---|---|
| **Community** | Free | 1, capped at 100 types | Unlimited public repos |
| **Teams** | $0.50 / type / month | Unlimited | — |
| **Pro** | $5 / type / month | Unlimited | Minimum $3,000/month spend |
| **Enterprise** | Custom | Unlimited | Self-hosted option, data isolation |

**What this means in practice:**
- **Public protos (OSS, public APIs)** — BSR is free forever. Unlimited public repositories on the Community tier.
- **Private protos in a company** — you hit paid tiers quickly. 50 message types × $0.50 = $25/month on Teams. The Pro tier's $3,000/month floor makes it firmly enterprise-targeted.
- **The `buf` CLI itself is always free** — linting, breaking change detection, and `buf generate` work entirely without the registry. You only need BSR if you want a hosted place to push and share protos.

#### Practical free alternative: `buf` CLI + Git (no registry)

For private company protos without the BSR cost, the most common approach is:

```bash
# Breaking change detection in CI against the main branch — free, no registry needed
buf breaking --against 'https://github.com/your-org/protos.git#branch=main'

# Linting — free
buf lint

# Generation — free
buf generate
```

This gives you all the tooling benefits (linting, breaking change detection, cleaner generation) with a Git repo as the source of truth instead of BSR.

```
                  ┌─────────────────────────────────┐
                  │   Buf Schema Registry            │
                  │   buf.build/moulimohann/poc      │
                  │                                  │
                  │   notes.proto   v1.0.0            │
                  │   notes.proto   v1.1.0            │
                  │   notes.proto   v1.2.0  ◄──────── │── buf push (owner team)
                  └─────────────────────────────────┘
                         │               │
                 buf generate       buf generate
                 (pin v1.2.0)       (pin v1.2.0)
                         │               │
                         ▼               ▼
                  python-server     api-gateway
                  (generates        (generates
                   servicer)         stub)
```

**Publishing side — the team that owns the proto:**

```yaml
# proto/buf.yaml
version: v2
modules:
  - path: .
    name: buf.build/moulimohann/poc
```

```bash
buf push   # publishes the current proto to BSR with a new commit SHA
```

**Consuming side — any team that needs it:**

```yaml
# buf.gen.yaml in the consumer's repo
version: v2
plugins:
  - remote: buf.build/protocolbuffers/python
    out: gen
  - remote: buf.build/grpc/python
    out: gen
deps:
  - buf.build/moulimohann/poc:v1.2.0   # pinned version
```

```bash
buf generate   # pulls the proto from BSR, generates stubs, writes to gen/
```

The consuming team never touches the `.proto` file directly. They declare a versioned dependency and run `buf generate`. The stubs appear in their `gen/` folder exactly as if they had run `protoc` themselves — but the source of truth is the registry, not a local file.

---

### Approach B — Git monorepo (used by Google, Uber, Lyft internally)

All `.proto` files for the entire organisation live in one repository. Every service owns a subdirectory:

```
company-protos/
├── notes/
│   └── v1/
│       └── notes.proto        ← owned by Notes team
├── products/
│   └── v1/
│       └── products.proto     ← owned by Products team
└── payments/
    └── v1/
        └── payments.proto
```

Each application repo declares a dependency on this monorepo (via git submodule, Bazel, or a package manager). CI enforces compatibility checks — a PR to `notes.proto` that removes a field or renumbers a tag fails the build with a breaking change error before it ever merges. No team can silently break another.

This is how Google manages thousands of `.proto` files internally. The proto repo becomes the **contract layer** between all services.

---

## Compatibility rules — what a registry enforces

Both approaches enforce compatibility levels so you cannot accidentally break consumers.

### The three levels

| Level | Rule |
|---|---|
| **BACKWARD** | New code can read data written by old code |
| **FORWARD** | Old code can read data written by new code |
| **FULL** | Both — all changes are purely additive |

### Safe changes (always allowed)

```protobuf
// Adding a new optional field — old clients receive tag 4 and silently skip it
message Note {
  string id     = 1;
  string title  = 2;
  string body   = 3;
  string author = 4;   // ← new, safe
}

// Adding a new RPC — old stubs simply never call it
service NotesService {
  rpc CreateNote  (CreateNoteRequest)  returns (CreateNoteResponse);
  rpc GetNote     (GetNoteRequest)     returns (Note);
  rpc StreamNotes (StreamNotesRequest) returns (stream Note);
  rpc DeleteNote  (DeleteNoteRequest)  returns (DeleteNoteResponse);  // ← new, safe
}
```

### Breaking changes (rejected by the registry)

```protobuf
// BREAKING — tag numbers swapped
// A client reading tag 2 now gets the body when it expected the title
message Note {
  string id    = 1;
  string body  = 2;   // ← was title (tag 2), now body
  string title = 3;   // ← was body (tag 3), now title
}

// BREAKING — field removed
// Old clients reading tag 2 get nothing; they silently see an empty string
message Note {
  string id   = 1;
  // title removed
  string body = 3;
}

// BREAKING — field type changed
// string and int32 have different wire encodings; decoder will misread the bytes
message Note {
  string id    = 1;
  int32  title = 2;   // ← was string
  string body  = 3;
}
```

Breaking change detection with `buf`:

```bash
# Check current proto against what is in main branch
buf breaking --against 'https://github.com/moulimohann/grpc-poc.git#branch=main'

# Or against a specific BSR version
buf breaking --against 'buf.build/moulimohann/poc:v1.2.0'
```

If any breaking change is detected, `buf` exits with a non-zero code and prints exactly which rule was violated. This runs in CI on every PR that touches a `.proto` file.

---

## Versioning strategies

### Strategy 1 — Additive-only on the same package

Never remove or renumber fields. Only add. The proto evolves in place and all consumers stay compatible forever.

```protobuf
// v1.0.0
message Note { string id = 1; string title = 2; string body = 3; }

// v1.1.0 — author added, all existing consumers unaffected
message Note { string id = 1; string title = 2; string body = 3; string author = 4; }
```

### Strategy 2 — Package versioning for true breaking changes

When a breaking redesign is unavoidable, mint a new package. Both versions coexist in the registry. Consumers migrate on their own schedule.

```
proto/
├── notes/v1/notes.proto    ← package notes.v1  (still served, old clients use this)
└── notes/v2/notes.proto    ← package notes.v2  (new design, consumers opt in)
```

```protobuf
// notes/v1/notes.proto
package notes.v1;

// notes/v2/notes.proto — completely different shape if needed
package notes.v2;
message Note { string id = 1; string title = 2; string content = 3; string author = 4; }
```

The registry serves both. No consumer is forced to migrate. The owner team deprecates v1 only after all consumers have moved.

---

## How this project would look with Buf

### Current state

```
proto/notes.proto        ← manually copied to each service
proto/products.proto     ← manually copied to each service
scripts/gen_proto.sh     ← runs protoc directly, fixes imports by hand
```

Pain points:
- No enforcement that `python-server` and `api-gateway` have the same version of `notes.proto`
- No automated breaking change detection
- Import fix `sed` hack to work around `protoc` output
- Two separate `protoc` invocations for notes (one per destination)

### With Buf

**`proto/buf.yaml`** — declares this as a publishable module:

```yaml
version: v2
modules:
  - path: .
    name: buf.build/moulimohann/grpc-poc
```

**`buf.gen.yaml`** at the project root — replaces `scripts/gen_proto.sh`:

```yaml
version: v2
clean: true
plugins:
  - remote: buf.build/protocolbuffers/python
    out: python-server/gen
  - remote: buf.build/grpc/python
    out: python-server/gen

  - remote: buf.build/protocolbuffers/python
    out: api-gateway/gen
  - remote: buf.build/grpc/python
    out: api-gateway/gen

  - remote: buf.build/protocolbuffers/go
    out: go-server/gen
    opt: paths=source_relative
  - remote: buf.build/grpc/go
    out: go-server/gen
    opt: paths=source_relative
```

**`scripts/gen_proto.sh`** becomes one line:

```bash
buf generate
```

Buf handles the relative imports automatically — no `sed` hack needed.

**CI breaking change check** (`.github/workflows/proto.yml`):

```yaml
- name: Check for breaking changes
  run: buf breaking --against 'https://github.com/moulimohann/grpc-poc.git#branch=main'
```

**Publishing when a change is approved:**

```bash
buf push   # pushes to buf.build/moulimohann/grpc-poc with a new commit SHA
```

**Consuming teams pin a version in their `buf.gen.yaml`:**

```yaml
deps:
  - buf.build/moulimohann/grpc-poc:a1b2c3d4   # exact commit SHA
```

They run `buf generate` and get stubs without ever needing the `.proto` file locally.

---

## Buf linting — enforcing style consistency

Beyond compatibility, `buf lint` enforces naming conventions across all proto files:

```bash
buf lint
```

Example rules it checks:

| Rule | Example violation |
|---|---|
| Field names must be `snake_case` | `noteId` instead of `note_id` |
| Message names must be `PascalCase` | `createNote` instead of `CreateNote` |
| RPCs must have unique request/response types | Two RPCs sharing a request message |
| Enums must have a zero value | Missing `UNKNOWN = 0` |
| Packages must match directory structure | `package notes` in `products/` dir |

These are configured in `buf.yaml`:

```yaml
version: v2
lint:
  use:
    - STANDARD   # the full recommended ruleset
```

---

## Comparison: manual sharing vs schema registry

| | Manual (this project) | `buf` CLI + Git (free) | BSR hosted registry |
|---|---|---|---|
| Source of truth | Local files, manually synced | Git repo (mono or shared) | `buf.build` hosted |
| Breaking change detection | None | `buf breaking` in CI | `buf breaking` in CI |
| Code generation | `protoc` + `sed` hack | `buf generate` (clean) | `buf generate` (clean) |
| Cross-team visibility | None | Git PR notifications | Registry UI + notifications |
| Versioning | Git history | Git commits / tags | Explicit commit SHAs on BSR |
| Cost | Free | Free | Free for public; paid for private |
| Best for | Small projects, single team | Private company protos at scale | OSS / public APIs, or orgs with budget |

---

## Key concepts summary

| Concept | What it means |
|---|---|
| **Schema registry** | Central versioned store for `.proto` files — the contract layer between services |
| **Buf CLI** | Modern `protoc` replacement with linting, breaking change detection, and registry integration |
| **BSR** | Buf Schema Registry — hosted at `buf.build`, stores proto modules with versioning |
| **Breaking change** | Any change that causes existing generated stubs to misread the wire format — tag renumber, field removal, type change |
| **Additive-only** | The safe evolution strategy — only add fields and RPCs, never remove or renumber |
| **Package versioning** | Minting `v2` of a package when a breaking redesign is unavoidable, letting consumers migrate on their own schedule |
| **`buf generate`** | Pulls protos from the registry, runs code generation for all configured languages in one command |
| **`buf breaking`** | Compares current proto against a baseline and fails if any breaking change is detected |
| **`buf lint`** | Enforces naming and structural conventions across all proto files |
| **Proto drift** | What happens without a registry — each team's copy of a `.proto` quietly diverges until production breaks |
