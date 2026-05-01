FROM python:3.11-slim

WORKDIR /app

# Dependências do sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Instala dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o código
COPY . .

# Permissão de execução para o entrypoint
RUN chmod +x /app/entrypoint.sh

# Cria diretório para os arquivos gerados
RUN mkdir -p /app/generated

EXPOSE 50051 8000

ENTRYPOINT ["/app/entrypoint.sh"]
