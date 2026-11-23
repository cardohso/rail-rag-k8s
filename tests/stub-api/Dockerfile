FROM python:3.12-slim
RUN useradd --create-home --uid 1000 app
USER app
COPY --chown=app stub.py /home/app/stub.py
CMD ["python", "/home/app/stub.py"]
