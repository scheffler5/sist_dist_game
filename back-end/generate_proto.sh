#!/bin/bash
# Gera os arquivos Python a partir do .proto
# Execute localmente com: bash generate_proto.sh
set -e

mkdir -p generated

python -m grpc_tools.protoc \
  -I ./protos \
  --python_out=./generated \
  --grpc_python_out=./generated \
  ./protos/game.proto

# Corrige imports relativos gerados pelo protoc
sed -i 's/^import game_pb2/from generated import game_pb2/' generated/game_pb2_grpc.py

# Cria __init__.py
touch generated/__init__.py

echo "✅ Arquivos gerados em ./generated/"
