FROM python:3.12-slim
LABEL org.opencontainers.image.source="https://github.com/singularis/raspberry_pi"
WORKDIR /app
COPY requirements.txt .
RUN apt-get update \
 && apt-get install -y --no-install-recommends openssh-client iputils-ping \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir -r requirements.txt
COPY *.py ./
USER 65534
EXPOSE 8010
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8010"]
