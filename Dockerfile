FROM python:3.11-slim AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

FROM python:3.11-slim

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app /app

ENV FLOWPILOT_ENV=production
ENV FLOWPILOT_HOST=0.0.0.0
ENV FLOWPILOT_PORT=7860
ENV FLOWPILOT_AUTH_ENABLED=true

EXPOSE 7860 8000

ENTRYPOINT ["python", "-m", "flowpilot"]
CMD ["serve", "--host", "0.0.0.0", "--port", "7860"]
