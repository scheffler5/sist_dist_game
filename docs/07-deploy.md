# 7. Deploy e operação

## Pré-requisitos

- **Docker Engine** (ou Docker Desktop).
- **Docker Compose v2** (já vem com versões recentes do Docker).
- Para acesso na LAN a partir de WSL2: PowerShell admin no Windows.

Sem dependências locais de Python, Node, gRPC tools — tudo é construído no container.

## docker-compose.yml — visão geral

Três serviços e uma rede:

```yaml
services:
  mongodb:                  # banco
    image: mongo:7
    healthcheck: {...}      # mongosh ping
    volumes: [mongo_data:/data/db]

  backend:                  # gRPC server + gateway
    build: ./back-end
    depends_on:
      mongodb: { condition: service_healthy }
    environment: { MONGO_URI, GRPC_HOST, ... }
    ports: ["8000:8000", "50051:50051"]

  frontend:                 # nginx
    build: ./front-end
    depends_on: [backend]
    ports: ["80:80"]

volumes:
  mongo_data:               # persistência do mongo

networks:
  game-network:             # rede interna entre os 3
```

- **Ordem de boot**: mongo → backend → frontend.
- O backend só inicia depois do `mongo` estar `healthy` (probe `db.adminCommand('ping')`).
- A rede `game-network` permite ao backend resolver `mongodb` e ao frontend resolver `backend` por nome de serviço.

## Subindo a aplicação

```bash
docker compose up -d --build
```

- `-d` desanexa (vai pra background).
- `--build` recompila as imagens (ignore se nada mudou).

Ao final você terá:

```
NAME                 STATUS    PORTS
guessgame-mongodb    Up (h)    27017/tcp                   (interno)
guessgame-backend    Up        0.0.0.0:8000, 0.0.0.0:50051
guessgame-frontend   Up        0.0.0.0:80
```

Acesse: <http://localhost>.

## Comandos do dia-a-dia

```bash
# status
docker compose ps

# logs em tempo real
docker compose logs -f backend
docker compose logs -f frontend
docker compose logs -f mongodb

# restart sem rebuild (rápido)
docker compose restart backend

# rebuild quando o código mudou
docker compose up -d --build backend     # só o backend
docker compose up -d --build             # tudo

# parar (mantém volumes e imagens)
docker compose down

# parar e apagar volumes (limpeza completa)
docker compose down -v

# entrar num container para inspecionar
docker compose exec backend bash
docker compose exec mongodb mongosh guessgame

# health check do gateway
curl http://localhost:8000/health
```

## Acesso na rede local (LAN)

Por padrão, os containers ouvem em `0.0.0.0`, então o jogo já está acessível para qualquer um que possa alcançar o IP da máquina host.

### Linux puro

Basta o IP da interface — nada de port forwarding extra. Se o firewall (`ufw`/`firewalld`) estiver ativo, libere `tcp/80` e `tcp/8000`.

### macOS

Mesmo caso — Docker Desktop expõe as portas no host.

### Windows com WSL2

WSL2 NÃO expõe automaticamente portas para a LAN externa. É preciso fazer **port forwarding** no Windows.

Descubra o IP do WSL:

```bash
hostname -I    # dentro do WSL → ex: 172.17.236.11
```

E o IP do Windows na LAN com `ipconfig` no PowerShell (procure "IPv4 Address" do adaptador Wi-Fi/Ethernet, ex: `192.168.30.7`).

No **PowerShell como administrador** no Windows:

```powershell
netsh interface portproxy add v4tov4 listenport=80   listenaddress=0.0.0.0 connectport=80   connectaddress=<IP-WSL>
netsh interface portproxy add v4tov4 listenport=8000 listenaddress=0.0.0.0 connectport=8000 connectaddress=<IP-WSL>

New-NetFirewallRule -DisplayName "WSL AdivinhAi 80"   -Direction Inbound -LocalPort 80   -Protocol TCP -Action Allow
New-NetFirewallRule -DisplayName "WSL AdivinhAi 8000" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow
```

Verifique:

```powershell
netsh interface portproxy show all
```

Acesse de outro dispositivo da mesma Wi-Fi:

```
http://<IP-WINDOWS-LAN>     # ex: http://192.168.30.7
```

### Reverter

```powershell
netsh interface portproxy reset
Remove-NetFirewallRule -DisplayName "WSL AdivinhAi 80"
Remove-NetFirewallRule -DisplayName "WSL AdivinhAi 8000"
```

> **Cuidado**: o IP do WSL muda a cada restart. Se reinicializar o PC ou WSL, refaça o `portproxy add` com o novo IP.

## Variáveis de ambiente

Configuradas em `docker-compose.yml`:

| Variável | Padrão | Onde |
|---|---|---|
| `GRPC_HOST` | `localhost` | backend (gateway → gRPC server, mesmo container) |
| `GRPC_PORT` | `50051` | backend |
| `HTTP_PORT` | `8000` | backend |
| `MONGO_URI` | `mongodb://mongodb:27017` | backend |
| `MONGO_DB` | `guessgame` | backend |
| `MONGO_INITDB_DATABASE` | `guessgame` | mongodb |

Se quiser sobrescrever, edite o compose ou crie um `docker-compose.override.yml`.

## Estrutura de boot do backend

[`back-end/entrypoint.sh`](../back-end/entrypoint.sh):

```bash
#!/bin/bash
set -e

# 1. Gera os stubs gRPC a partir do .proto
python -m grpc_tools.protoc \
  -I /app/protos \
  --python_out=/app/generated \
  --grpc_python_out=/app/generated \
  /app/protos/game.proto

sed -i 's/^import game_pb2/from generated import game_pb2/' /app/generated/game_pb2_grpc.py
touch /app/generated/__init__.py

# 2. Sobe o servidor gRPC em background
python /app/game_server.py &

# 3. Espera o gRPC ficar pronto
until python -c "import grpc; grpc.channel_ready_future(...).result(timeout=1)" 2>/dev/null; do
  sleep 1
done

# 4. Sobe o gateway (uvicorn) em foreground
exec python -m uvicorn gateway:app --host 0.0.0.0 --port "${HTTP_PORT:-8000}"
```

Os dois processos rodam no mesmo container. Quando o gateway morrer, o container reinicia (policy `unless-stopped`), levando junto o gRPC server (que fica em background).

## Logs e debugging

### Onde olhar

```
docker compose logs backend          # FastAPI/uvicorn + gRPC server (mesmo stdout)
docker compose logs frontend         # access.log do nginx
docker compose logs mongodb          # log do banco
```

### Filtrando

```bash
docker compose logs backend | grep ERROR
docker compose logs backend --since 5m
docker compose logs -f --tail=100 backend
```

### Inspecionando o estado do banco

```bash
docker compose exec mongodb mongosh guessgame
```

```javascript
// dentro do mongosh
db.chat.find({game_id: "ABC123"}).sort({timestamp: 1})
db.chat.countDocuments({game_id: "ABC123"})
db.chat.deleteMany({game_id: "ABC123"})    // limpeza manual
db.chat.getIndexes()
```

### Inspecionando o estado em memória do backend

Como tudo vive em memória do processo Python, não há jeito direto. Opções:

- Adicionar uma rota debug no gateway (não existe atualmente — seria um hook simples no `game_manager`).
- Acompanhar os eventos via WebSocket: o `initial_state` reflete o estado completo.
- Logs do gRPC server vão para o stdout do container.

## Problemas comuns

### "WebSocket fechado, reconectando em 3s..." em loop

Causas:
- Backend caiu — `docker compose logs backend`.
- Nginx parou — `docker compose logs frontend`.
- O nginx pode estar mudando o `Connection`/`Upgrade` errado se a config foi alterada.

Verifique o `nginx.conf`:

```nginx
location /ws/ {
    proxy_pass http://backend:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 3600s;
}
```

### "Jogo não encontrado" depois de criar a sala

Causas prováveis:
- O backend reiniciou. O `_games` é em memória, sumiu junto.
- Solução: voltar ao login e criar uma sala nova.

### Mudanças no `app.js` não aparecem

O Tailwind CDN compila os estilos no carregamento da página, e o nginx tem `Cache-Control: no-cache, no-store, must-revalidate` para o html, mas o navegador pode ainda cachear o JS. Force `Ctrl+Shift+R`.

### Mudanças em `game.proto` não tomam efeito

O proto é compilado **no boot do container** pelo `entrypoint.sh`. Reconstruir não basta se o container já estiver rodando com a versão antiga em RAM. Faça:

```bash
docker compose up -d --build backend
```

Não rode com `--no-deps` se quiser que o gateway pegue as novas classes proto.

### Porta 80 ocupada

Outro serviço local (Apache, IIS) pode estar usando. Mude o mapeamento em `docker-compose.yml`:

```yaml
frontend:
  ports:
    - "8080:80"   # acessa em http://localhost:8080
```

Se mudar a porta do gateway (8000), não esqueça que o `app.js` se conecta no mesmo `location.host` — então o gateway precisa ser acessível via nginx no mesmo host/porta da página, e isso já vem coberto pelo proxy `/api/` e `/ws/`.

### MongoDB demora muito para "ficar saudável"

A primeira inicialização cria o volume e os índices. Em discos lentos pode levar 20–30s. Se `backend` falha ao subir com timeout do `serverSelectionTimeoutMS=5000`, ele continua mesmo assim — o chat fica desabilitado (mensagens vão pro broadcast mas não persistem). Logs:

```
MongoDB não disponível: ... Chat sem persistência.
```

Reinicie o backend após o mongo subir:

```bash
docker compose restart backend
```

## Atualizando o código

Em desenvolvimento típico:

```bash
# editou algo no back-end:
docker compose up -d --build backend

# editou algo no front-end:
docker compose up -d --build frontend

# editou algo em ambos:
docker compose up -d --build

# editou só o nginx.conf:
docker compose restart frontend
```

## Limpeza completa

Para começar do zero (apaga o histórico de chat, imagens, volumes):

```bash
docker compose down -v
docker compose build --no-cache
docker compose up -d
```

## Onde NÃO mexer

- O `entrypoint.sh` mexe nos imports gerados com `sed` — alterar a estrutura de `/app/generated/` provavelmente quebra. Se precisar, regenere localmente e rode `back-end/generate_proto.sh`.
- A rede `game-network` é o que permite os nomes `mongodb` e `backend` resolverem. Não use `network_mode: host` ou DNS externo.
