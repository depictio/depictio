FROM python:3.8-slim

WORKDIR /app
COPY ./app.py /app
RUN pip install dash dash-core-components dash-html-components requests

CMD ["python", "app.py"]
