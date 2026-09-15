FROM python:3.11-slim

# g++ is required to compile Stonkfly's event-driven LIF kernel (kernel.cpp)
# on first brain load; git to vendor Stonkfly at a pinned commit.
RUN apt-get update \
    && apt-get install -y --no-install-recommends g++ git curl \
    && rm -rf /var/lib/apt/lists/*

# Stonkfly is vendored unmodified (MIT). Its trading dependencies
# (coinbase-agentkit, broker) are NOT installed - we only import the
# stonkfly.neural package via PYTHONPATH.
ARG STONKFLY_REF=78ef3e05ab0fa086032098558d893667068944a0
RUN git clone https://github.com/nftechie/stonkfly /opt/stonkfly \
    && git -C /opt/stonkfly checkout ${STONKFLY_REF}

ENV PYTHONPATH=/opt/stonkfly \
    STONKFLY_DATA=/data \
    PYTHONUNBUFFERED=1

WORKDIR /srv
COPY requirements.txt /srv/requirements.txt
RUN pip install --no-cache-dir -r /srv/requirements.txt

COPY app /srv/app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
