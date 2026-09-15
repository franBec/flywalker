FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    DATA_DIR=/data

WORKDIR /srv
COPY requirements.txt /srv/requirements.txt
RUN pip install --no-cache-dir -r /srv/requirements.txt

COPY corridor.py frames.py mockcorridor.py policies.py walk.py replay.py /srv/

CMD ["python", "walk.py"]
