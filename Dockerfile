FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=7860 PUBLIC_MODE=true
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd -m -u 10001 agent
COPY . .
RUN mkdir -p /app/workspace && chown -R agent:agent /app
USER agent
EXPOSE 7860
CMD ["sh","-c","uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
