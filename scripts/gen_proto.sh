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
  "$PYTHON" -c "
import re, sys
path = sys.argv[1]
text = open(path).read()
fixed = re.sub(r'^import (\S+_pb2) as', r'from . import \1 as', text, flags=re.MULTILINE)
open(path, 'w').write(fixed)
" "$f"
done

touch "$ROOT/python-server/gen/__init__.py"
touch "$ROOT/api-gateway/gen/__init__.py"

echo "Done."
