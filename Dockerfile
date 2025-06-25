# Use an official Python runtime as a parent image
# We choose a slim-buster image for smaller size
FROM python:3.9-slim-buster

WORKDIR /app

COPY requirements.txt .


RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

EXPOSE 8000

CMD ["uvicorn", "API.app:app", "--host", "0.0.0.0", "--port", "8000"]

