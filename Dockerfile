FROM opendronemap/opendronemap

COPY requirements.txt .
RUN pip install --user -r requirements.txt

RUN mkdir -p /code/logs
COPY server.py .
ENTRYPOINT python server.py --port=5000 >> /code/logs/log 2>&1
