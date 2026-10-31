FROM python:3.14-slim

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY . /opt/smartproxy/policy
WORKDIR /opt/smartproxy
ENV PYTHONUNBUFFERED=1

EXPOSE 8090 8443
CMD ["python", "-m", "policy.serve"]
