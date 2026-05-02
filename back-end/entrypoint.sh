#!/bin/bash
set -e

echo "=== Gerando código gRPC a partir do proto ==="
mkdir -p /app/generated
python -m grpc_tools.protoc \
  -I /app/protos \
  --python_out=/app/generated \
  --grpc_python_out=/app/generated \
  /app/protos/game.proto

# Corrige imports relativos gerados pelo protoc
sed -i 's/^import game_pb2/from generated import game_pb2/' /app/generated/game_pb2_grpc.py

# Cria __init__.py para o pacote generated
touch /app/generated/__init__.py

echo "=== Iniciando servidor gRPC (porta 50051) ==="
python /app/game_server.py &

echo "=== Aguardando gRPC iniciar ==="
until python -c "import grpc; grpc.channel_ready_future(grpc.insecure_channel('localhost:${GRPC_PORT:-50051}')).result(timeout=1)" 2>/dev/null; do
  sleep 1
done

echo "=== Iniciando gateway HTTP/WebSocket (porta 8000) ==="
exec python -m uvicorn gateway:app \
  --host 0.0.0.0 \
  --port "${HTTP_PORT:-8000}" \
  --log-level info
