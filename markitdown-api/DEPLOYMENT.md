# Guia de Deploy na Cloud

Este guia descreve os passos necessários para empacotar o microserviço **MarkItDown API** em um container Docker e realizar o deploy em provedores de Cloud.

## 1. O que você precisa ter instalado

Para construir e testar a imagem do container localmente (antes de subir para a cloud), você precisará de:

*   **Docker:** (Pode ser o Docker Desktop, OrbStack, ou o Docker Engine padrão da sua máquina).
*   **Git:** Para criar um repositório e enviar o código para plataformas que fazem deploy automático (como GitHub/GitLab).

---

## 2. Preparando os arquivos para o Docker

### O `Dockerfile`
O `Dockerfile` é a "receita" que ensina como a nossa máquina virtual deve ser criada. Crie um arquivo chamado `Dockerfile` (sem nenhuma extensão) na raiz do projeto (`markitdown-api/`) com o seguinte conteúdo:

```dockerfile
# 1. Usa uma imagem oficial do Python, leve e otimizada (vamos usar 3.12 como solicitado no projeto original)
FROM python:3.12-slim

# 2. Define o diretório de trabalho dentro do container
WORKDIR /app

# 3. Variáveis de ambiente para otimizar o comportamento do Python
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 4. Instala dependências do sistema que podem ser necessárias para converter PDFs e lidar com XML (fonts, libs C)
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 5. Copia o arquivo de dependências
COPY requirements.txt .

# 6. Atualiza o pip e instala as bibliotecas Python
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 7. Copia todo o código da nossa aplicação para a pasta /app do container
COPY ./app ./app

# 8. Expõe a porta que a aplicação vai rodar
EXPOSE 8000

# 9. Comando que será rodado quando o container ligar
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### O `.dockerignore`
Assim como o `.gitignore`, esse arquivo evita que pastas inúteis (ou sensíveis) da sua máquina local sejam copiadas para dentro do Docker. Crie um `.dockerignore` na raiz:

```text
venv/
env/
.venv/
__pycache__/
*.pyc
.env
.pytest_cache/
.DS_Store
```

---

## 3. Como Construir e Testar a Imagem (Local)

Com os arquivos criados e o Docker rodando na sua máquina, abra o terminal na pasta do projeto e execute:

**1. Construir a imagem (Build):**
```bash
docker build -t markitdown-api .
```

**2. Executar o container:**
```bash
docker run -d -p 8000:8000 --name meu-markitdown markitdown-api
```

Pronto! A API estará rodando dentro do Docker no seu `http://localhost:8000/docs`. Para parar e remover, use `docker rm -f meu-markitdown`.

---

## 4. Como Executar na Cloud

A sua API agora é um **Container Docker**. A grande vantagem disso é que ela pode rodar em literalmente qualquer lugar. Aqui estão as abordagens mais comuns:

### Opção A: Plataformas fáceis (PaaS) - Rendimento Rápido
Plataformas como **Render**, **Railway** ou **Fly.io**.
1. Envie seu código para um repositório no **GitHub**.
2. Conecte o repositório na plataforma escolhida.
3. Eles vão ler automaticamente o seu `Dockerfile`, construir a imagem e te entregar um link (ex: `https://sua-api.onrender.com`).

### Opção B: Serverless Containers - (Recomendado para Escala)
Opções como **Google Cloud Run** ou **AWS App Runner**.
1. No **Cloud Run**, você pode instalar o `gcloud CLI` e executar um único comando na pasta do projeto:
   ```bash
   gcloud run deploy markitdown-api --source .
   ```
2. O Google cuidará de buildar a imagem e colocar no ar. Você só paga quando receber requisições, e a API pode escalar infinitamente ou zerar o uso de noite.

### Opção C: Máquina Virtual Clássica (VPS)
Se você alugou um servidor na **DigitalOcean**, **Hetzner** ou **AWS EC2**:
1. Acesse o servidor via SSH.
2. Instale o Docker lá dentro.
3. Clone o seu projeto com Git.
4. Rode os comandos de Build e Run que ensinamos na Etapa 3.

---

## 5. Dicas Extras de Produção

1. **Tamanho do Upload:** Nossa API tem limite de 50MB. Alguns Proxies/Nuvens (como Cloudflare ou o NGINX padrão) costumam bloquear uploads maiores que 1MB por padrão. Lembre-se de configurar o *Max Body Size* na Cloud.
2. **Tempo de Resposta (Timeout):** O MarkItDown pode ser pesado ao converter PDFs gigantes (200+ páginas). Em serviços como AWS Lambda ou Cloud Run, o tempo máximo de resposta padrão pode ser de 30 ou 60 segundos. Não se esqueça de aumentar esse timeout para ~5 minutos nas configurações da Cloud se for focar em documentos grandes.
