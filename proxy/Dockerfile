# The proxy image for an installed package (make dist). The addon is copied
# in, so the installed compose file mounts no source. The development stack
# runs the base image with ./proxy mounted instead.
# make dist passes the proxy image from docker-compose.yml.
ARG MITMPROXY_IMAGE=mitmproxy/mitmproxy:12.2.3
FROM ${MITMPROXY_IMAGE}

COPY . /opt/daywarden/
