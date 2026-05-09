# Documentação — AdivinhAí

Esta pasta contém a documentação técnica do projeto, organizada por etapas. Cada documento aprofunda um aspecto específico do sistema. Para uma visão geral e instruções de setup, veja o [README principal](../README.md).

## Índice

1. [Arquitetura geral](01-arquitetura.md) — componentes, fluxos de comunicação, decisões de design
2. [RPC e contrato gRPC](02-rpc-grpc.md) — `game.proto`, RPCs unários e streaming, mensagens
3. [Gateway HTTP / WebSocket](03-gateway-http-websocket.md) — bridge browser → gRPC, REST, eventos em tempo real
4. [Funcionamento do jogo](04-funcionamento.md) — máquina de estados, regras, mecânicas, pontuação
5. [Persistência e estado](05-persistencia.md) — estado em memória, MongoDB, lifecycle do chat
6. [Frontend](06-frontend.md) — telas, render, eventos do cliente
7. [Deploy e operação](07-deploy.md) — Docker Compose, LAN, debugging, troubleshooting

## Convenções

- Diagramas em ASCII para portabilidade.
- Trechos de código com referência a arquivo e linha (`back-end/services/spy.py:30`) para navegação rápida.
- Português nas explicações; identificadores e mensagens de log em inglês quando assim estão no código.
