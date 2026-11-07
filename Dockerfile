FROM python:3.12-slim
WORKDIR /srv
RUN addgroup --system crosslist && adduser --system --ingroup crosslist crosslist && mkdir /data && chown crosslist:crosslist /data
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
USER crosslist
ENV CROSSLIST_DB=/data/crosslist.sqlite3 PYTHONDONTWRITEBYTECODE=1
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
