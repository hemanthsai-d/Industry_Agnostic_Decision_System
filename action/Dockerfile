FROM python:3.13-slim

LABEL maintainer="hemanthsai-d"
LABEL org.opencontainers.image.source="https://github.com/hemanthsai-d/Industry_Agnostic_Decision_System"
LABEL org.opencontainers.image.description="AI Decision Platform — Customer Support Triage Action"

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /action

COPY requirements.txt /action/requirements.txt
RUN pip install --no-cache-dir -r /action/requirements.txt

COPY app /action/app
COPY artifacts /action/artifacts
COPY policy /action/policy
COPY action/entrypoint.py /action/entrypoint.py

ENTRYPOINT ["python", "/action/entrypoint.py"]
