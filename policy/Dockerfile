# The parent portal is built in a Node stage. The Python image copies in only
# the built files, so the image, and the make dist package, need no Node.
# The portal imports the drag-and-drop it shares with the child's parts of
# speech page from static/, one level above it, as in the repository.
FROM node:24.22.2-slim AS portal
WORKDIR /portal
COPY portal/package.json portal/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY static/word_sort.js static/word_sort.d.ts /static/
COPY portal/ ./
RUN npm run build

FROM python:3.14-slim

# git commits the parent portal's saves to the config history. ffmpeg, built
# with libopus, cuts the recordings made in the parent portal.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY --exclude=portal . /opt/daywarden/policy
COPY --from=portal /portal/dist /opt/daywarden/policy/portal/dist
WORKDIR /opt/daywarden
ENV PYTHONUNBUFFERED=1

EXPOSE 8090 8443
CMD ["python", "-m", "policy.serve"]
