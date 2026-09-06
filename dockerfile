FROM python:3.12-slim

WORKDIR /code

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src
COPY main.py .
COPY shelly_collector.py .
COPY shelly_history_collector.py .
COPY shelly_p1_collector.py .

CMD ["python", "main.py", "--loop", "5"]