FROM opendronemap/opendronemap

COPY requirements.txt .
RUN pip install --user -r requirements.txt

COPY server.py .
ENTRYPOINT python server.py --port=5000 >> log 2>&1
