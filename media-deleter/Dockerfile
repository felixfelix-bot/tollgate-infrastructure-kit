FROM python:3.13-slim

# Stdlib only: no pip install, no network at build time beyond the base image.
# Keeping the dependency set empty is the point — this sidecar is a security
# boundary, so it carries no third-party code to audit or patch.
WORKDIR /app
COPY buzz_media_deleter.py /app/buzz_media_deleter.py

RUN useradd --system --uid 10001 --create-home deleter \
    && chown -R deleter:deleter /app
USER deleter

EXPOSE 8099

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD ["python3", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8099/healthz', timeout=3).status==200 else 1)"]

ENTRYPOINT ["python3", "-u", "/app/buzz_media_deleter.py"]
