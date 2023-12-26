FROM python:3.11.7-bookworm
WORKDIR /app
COPY ./requirements.txt /app
RUN pip install -r requirements.txt
COPY . .
EXPOSE 5000
ENV FLASK_APP=apps/frontend/supertl2.py
CMD ["flask", "run", "--host", "0.0.0.0"]