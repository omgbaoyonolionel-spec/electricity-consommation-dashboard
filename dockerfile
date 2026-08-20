FROM python:3.12-slim

WORKDIR /code

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app
COPY alembic.ini .
COPY alembic/ ./alembic

CMD ["python", "-m", "app.main", "--loop", "300"]