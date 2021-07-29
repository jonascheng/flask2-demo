FROM python:3.8-slim-buster

WORKDIR /app

COPY ./requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

COPY . /app

# ENTRYPOINT ["python"]
CMD ["python", "app.py"]
