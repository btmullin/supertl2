FROM python:3.11.7-bookworm
WORKDIR /app
COPY ./requirements.txt /app
RUN pip install -r requirements.txt
RUN apt update && apt install -y sqlite3
COPY . .
EXPOSE 5000
ENV FLASK_APP=apps/backend/supertl2.py
ENV PYTHONPATH=/app/apps/common
ENV FLASK_DEBUG=True
CMD ["flask", "run", "--host", "0.0.0.0"]

# If you ever want to build an image that just runs a bash shell to launch flask manually
# CMD ["/bin/bash"]