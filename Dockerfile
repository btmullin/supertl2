FROM python:3.11.7-bookworm
WORKDIR /app
COPY ./requirements.txt /app
RUN pip install -r requirements.txt
RUN apt update
RUN apt install sqlite3
COPY . .
EXPOSE 5000
ENV FLASK_APP=apps/frontend/supertl2.py
ENV PYTHONPATH=/app/apps/common
CMD ["flask", "run", "--host", "0.0.0.0"]

# If you ever want to build an image that just runs a bash shell to launch flask manually
# CMD ["/bin/bash"]