# Deep Dive: `scripts/gen_proto.sh`

This script is the single command that turns your `.proto` files into working code in every language in the project. You run it once after any `.proto` change and it regenerates all stubs — Go and Python — in the right places.

```bash
bash scripts/gen_proto.sh
```

---

## What it produces

```
scripts/gen_proto.sh
          │
          ├─ notes.proto ──► python-server/gen/notes_pb2.py
          │                  python-server/gen/notes_pb2_grpc.py
          │                  python-server/gen/__init__.py
          │
          ├─ notes.proto ──► api-gateway/gen/notes_pb2.py
          │                  api-gateway/gen/notes_pb2_grpc.py
          │
          ├─ products.proto ► go-server/gen/products.pb.go
          │                   go-server/gen/products_grpc.pb.go
          │
          └─ products.proto ► api-gateway/gen/products_pb2.py
                              api-gateway/gen/products_pb2_grpc.py
                              api-gateway/gen/__init__.py
```

---

## Line by line

### Line 1 — the shebang

```bash
#!/usr/bin/env bash
```

Tells the OS which interpreter to use. `#!/usr/bin/env bash` is portable — instead of hardcoding `/bin/bash` (which may not exist at that path on every system), it asks `env` to find `bash` in `$PATH`. Matters when the file is executed directly as `./scripts/gen_proto.sh`; ignored when you run `bash scripts/gen_proto.sh` explicitly.

---

### Line 2 — safety flags

```bash
set -euo pipefail
```

Three flags combined:

| Flag | Meaning |
|---|---|
| `-e` | Exit immediately if any command returns a non-zero exit code. Without this, a failed `protoc` invocation would be silently ignored and the script would continue with stale or missing stubs. |
| `-u` | Treat references to unset variables as errors. Without this, a typo like `$RROT` would silently expand to an empty string, producing a path like `/proto` instead of the real project root. |
| `-o pipefail` | In a pipeline like `cmd1 \| cmd2`, bash normally only checks the exit code of the last command. `pipefail` makes the whole pipeline fail if any command in it fails. |

Together these make the script fail loudly and early rather than producing broken output silently.

---

### Line 4 — finding the project root

```bash
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
```

Breaking it apart:

- `$0` — the path to the script itself, e.g. `scripts/gen_proto.sh`
- `dirname "$0"` — strips the filename, leaving `scripts/`
- `"$(dirname "$0")/.."` — appends `..` to navigate one level up to the project root
- `cd ... && pwd` — changes into that directory and prints its absolute path

The result stored in `ROOT` is always an absolute path, e.g. `/Users/moulimohann/projects/personal/python-grpc-poc`. Every subsequent path in the script is built on top of `ROOT`, so the script works regardless of which directory you run it from.

---

### Lines 5–10 — venv guard

```bash
PYTHON="$ROOT/api-gateway/.venv/bin/python"

if [ ! -f "$PYTHON" ]; then
  echo "ERROR: api-gateway venv not found. Run: cd api-gateway && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi
```

Python stubs are generated using `grpc_tools.protoc`, which is installed inside the `api-gateway` venv (it's in `api-gateway/requirements.txt`). Rather than assuming the system `python3` has it, the script pinpoints the exact venv Python.

`[ ! -f "$PYTHON" ]` checks that the file exists and is a regular file. If the venv hasn't been created yet, the script exits with code 1 and tells you exactly what to run to fix it. Without this guard, the next command would fail with a confusing "no such file or directory" error.

---

### Lines 12–21 — generating Python stubs for Notes (two destinations)

```bash
"$PYTHON" -m grpc_tools.protoc -I "$ROOT/proto" \
  --python_out="$ROOT/python-server/gen" \
  --grpc_python_out="$ROOT/python-server/gen" \
  "$ROOT/proto/notes.proto"

"$PYTHON" -m grpc_tools.protoc -I "$ROOT/proto" \
  --python_out="$ROOT/api-gateway/gen" \
  --grpc_python_out="$ROOT/api-gateway/gen" \
  "$ROOT/proto/notes.proto"
```

`grpc_tools.protoc` is a Python wrapper around the real `protoc` binary — it ships bundled inside `grpcio-tools` so you don't need a separate system `protoc` install for Python generation.

Each flag:

| Flag | Meaning |
|---|---|
| `-m grpc_tools.protoc` | Run `protoc` via the Python module |
| `-I "$ROOT/proto"` | The **import path** — where `protoc` looks when resolving `import` statements inside `.proto` files. Also determines how the output filename is computed: the input path is made relative to `-I`, so `$ROOT/proto/notes.proto` becomes `notes.proto`, producing output files named `notes_pb2.py` and `notes_pb2_grpc.py` |
| `--python_out=<dir>` | Where to write `notes_pb2.py` — the message classes (serialisation/deserialisation) |
| `--grpc_python_out=<dir>` | Where to write `notes_pb2_grpc.py` — the service glue (stub, servicer, registration) |
| Last argument | The `.proto` file to compile |

The command runs **twice** because two separate directories need copies of the notes stubs:
- `python-server/gen/` — the Notes gRPC server needs the servicer base class to implement
- `api-gateway/gen/` — the gateway needs the stub to call the Notes server as a client

---

### Lines 23–27 — generating Go stubs for Products

```bash
protoc -I "$ROOT/proto" \
  --go_out=paths=source_relative:"$ROOT/go-server/gen" \
  --go-grpc_out=paths=source_relative:"$ROOT/go-server/gen" \
  "$ROOT/proto/products.proto"
```

Here the system `protoc` binary is used directly (not the Python wrapper) because the target is Go. The Go plugins `protoc-gen-go` and `protoc-gen-go-grpc` must be on `$PATH`, installed via:

```bash
go install google.golang.org/protobuf/cmd/protoc-gen-go@latest
go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@latest
```

`protoc` discovers these plugins automatically by looking for executables named `protoc-gen-go` and `protoc-gen-go-grpc` in `$PATH`.

The key difference from the Python invocation: **`paths=source_relative`**.

Without it, `protoc` uses the `go_package` option in the proto to construct a nested output path, producing something like `go-server/gen/github.com/moulimohann/grpc-poc/go-server/gen/products.pb.go`. With `paths=source_relative`, it ignores the package path and writes the files flat into the output directory — `go-server/gen/products.pb.go` and `go-server/gen/products_grpc.pb.go`.

| Flag | Produces |
|---|---|
| `--go_out` | `products.pb.go` — the message structs and serialisation |
| `--go-grpc_out` | `products_grpc.pb.go` — the service interface and server/client glue |

---

### Lines 29–33 — generating Python stubs for Products (gateway only)

```bash
"$PYTHON" -m grpc_tools.protoc -I "$ROOT/proto" \
  --python_out="$ROOT/api-gateway/gen" \
  --grpc_python_out="$ROOT/api-gateway/gen" \
  "$ROOT/proto/products.proto"
```

The gateway calls the Go Products server, so it needs Python stubs for `products.proto` too. The Go server and the Python gateway share the same `.proto` contract but each generates stubs in their own language — this is the interoperability point. `python-server` does not get these because it has nothing to do with Products.

---

### Lines 35–40 — fixing relative imports

```bash
for f in "$ROOT/python-server/gen/"*_pb2_grpc.py "$ROOT/api-gateway/gen/"*_pb2_grpc.py; do
  [ -f "$f" ] || continue
  sed -i '' 's/^import \(.*_pb2\) as/from . import \1 as/' "$f" 2>/dev/null || \
  sed -i 's/^import \(.*_pb2\) as/from . import \1 as/' "$f"
done
```

`protoc` generates `*_pb2_grpc.py` with an absolute import:

```python
import notes_pb2 as notes__pb2   # what protoc generates
```

This works when `gen/` is the working directory, but breaks when it's used as a package (`from gen import notes_pb2_grpc`) because Python looks for `notes_pb2` at the top level rather than inside `gen/`. The fix is a relative import:

```python
from . import notes_pb2 as notes__pb2   # what sed replaces it with
```

The `.` means "look in the same package as this file" — i.e. inside `gen/`.

Breaking down the `sed` command:

| Part | Meaning |
|---|---|
| `-i ''` | Edit the file in-place. The `''` is required on macOS to mean "no backup file". |
| `'s/^import \(.*_pb2\) as/from . import \1 as/'` | Regex substitution: match any line starting with `import <x>_pb2 as`, capture `<x>_pb2` in `\1`, replace with `from . import <x>_pb2 as` |
| `2>/dev/null \|\| sed -i ...` | macOS `sed` uses `-i ''`; GNU `sed` on Linux uses `-i` with no argument. The `\|\|` fallback makes the script portable across both. |
| `[ -f "$f" ] \|\| continue` | Guards against the glob expanding to a literal string (e.g. `*_pb2_grpc.py`) when no files match yet — the loop skips that iteration instead of trying to `sed` a non-existent file. |

---

### Lines 42–43 — creating `__init__.py`

```bash
touch "$ROOT/python-server/gen/__init__.py"
touch "$ROOT/api-gateway/gen/__init__.py"
```

`touch` creates the file if it doesn't exist, or updates its timestamp if it does — a no-op on re-runs.

Without `__init__.py`, Python treats `gen/` as a plain directory, not a package. The import `from gen import notes_pb2` would fail with `ModuleNotFoundError`. The empty `__init__.py` marks `gen/` as a package so Python's import system can find modules inside it.

Go does not need this — Go uses directory-based packages automatically with no marker file required.

---

## Why two tools (`grpc_tools.protoc` vs `protoc`)

| | Python generation | Go generation |
|---|---|---|
| **Tool** | `python -m grpc_tools.protoc` | system `protoc` binary |
| **Plugins** | bundled inside `grpcio-tools` pip package | `protoc-gen-go` and `protoc-gen-go-grpc` on `$PATH` |
| **Output path control** | no `paths=` option needed | requires `paths=source_relative` to avoid nested dirs |
| **Installed via** | `pip install grpcio-tools` | `go install ...` + `brew install protobuf` |

---

## When to re-run

Re-run `bash scripts/gen_proto.sh` whenever you:

- Add a new field to an existing message
- Add a new RPC to a service
- Add a new message or service
- Change a field tag number (breaking — also update all existing data)
- Rename a service or package (breaking — update all import paths)

After re-running, restart the affected services so they pick up the new stubs.
