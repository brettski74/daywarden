# The parent portal is built in a Node stage. The Python image copies in only
# the built files, so the image, and the make dist package, need no Node.
FROM node:24.22.2-slim AS portal
WORKDIR /portal
COPY portal/package.json portal/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY portal/ ./
RUN npm run build

FROM python:3.14-slim

# git commits the parent portal's saves to the config history.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY --exclude=portal . /opt/daywarden/policy
COPY --from=portal /portal/dist /opt/daywarden/policy/portal/dist
WORKDIR /opt/daywarden
ENV PYTHONUNBUFFERED=1

EXPOSE 8090 8443
CMD ["python", "-m", "policy.serve"]
