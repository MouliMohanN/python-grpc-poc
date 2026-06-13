#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$ROOT/api-gateway/.venv/bin/python"

if [ ! -f "$PYTHON" ]; then
  echo "ERROR: api-gateway venv not found. Run: cd api-gateway && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

echo "==> Generating Python stubs for notes (python-server + api-gateway)"
"$PYTHON" -m grpc_tools.protoc -I "$ROOT/proto" \
  --python_out="$ROOT/python-server/gen" \
  --grpc_python_out="$ROOT/python-server/gen" \
  "$ROOT/proto/notes.proto"

"$PYTHON" -m grpc_tools.protoc -I "$ROOT/proto" \
  --python_out="$ROOT/api-gateway/gen" \
  --grpc_python_out="$ROOT/api-gateway/gen" \
  "$ROOT/proto/notes.proto"

echo "==> Generating Go stubs for products (go-server)"
protoc -I "$ROOT/proto" \
  --go_out=paths=source_relative:"$ROOT/go-server/gen" \
  --go-grpc_out=paths=source_relative:"$ROOT/go-server/gen" \
  "$ROOT/proto/products.proto"

echo "==> Generating Python stubs for products (api-gateway)"
"$PYTHON" -m grpc_tools.protoc -I "$ROOT/proto" \
  --python_out="$ROOT/api-gateway/gen" \
  --grpc_python_out="$ROOT/api-gateway/gen" \
  "$ROOT/proto/products.proto"

echo "==> Fixing relative imports in generated Python files"
for f in "$ROOT/python-server/gen/"*_pb2_grpc.py "$ROOT/api-gateway/gen/"*_pb2_grpc.py; do
  [ -f "$f" ] || continue
  sed -i '' 's/^import \(.*_pb2\) as/from . import \1 as/' "$f" 2>/dev/null || \
  sed -i 's/^import \(.*_pb2\) as/from . import \1 as/' "$f"
done

touch "$ROOT/python-server/gen/__init__.py"
touch "$ROOT/api-gateway/gen/__init__.py"

echo "Done."
