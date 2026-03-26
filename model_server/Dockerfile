FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app --home /home/app app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app /app/app
COPY artifacts /app/artifacts
COPY model_server /app/model_server

USER app

EXPOSE 9000

CMD ["python", "-m", "uvicorn", "model_server.app:app", "--host", "0.0.0.0", "--port", "9000"]
