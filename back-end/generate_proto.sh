#!/bin/bash
set -e

mkdir -p generated

python -m grpc_tools.protoc \
  -I ./protos \
  --python_out=./generated \
  --grpc_python_out=./generated \
  ./protos/game.proto

sed -i 's/^import game_pb2/from generated import game_pb2/' generated/game_pb2_grpc.py

touch generated/__init__.py

echo "✅ Arquivos gerados em ./generated/"
