FROM python:2.7.18-buster as js-build-stage

# Debian buster is EOL and no longer served by deb.debian.org: use the archive
RUN printf 'deb http://archive.debian.org/debian buster main\ndeb http://archive.debian.org/debian-security buster/updates main\n' > /etc/apt/sources.list
RUN apt-get -o Acquire::Check-Valid-Until=false update
RUN apt-get -y install p7zip-full

WORKDIR /opt
COPY dep/pyjs.7z .

WORKDIR /build
COPY src/percorso/js .
COPY dep/build_js.sh .

RUN bash ./build_js.sh

# Runtime su Python 3.9, ma sempre su Debian buster: cosi' GEOS/GDAL/PROJ
# restano le stesse versioni con cui gira lo stack Py2, e i binding GeoDjango
# di Django 1.5 si comportano identici -- cambia solo l'interprete.
FROM python:3.9-buster

WORKDIR /app

# Install required packages
RUN printf 'deb http://archive.debian.org/debian buster main\ndeb http://archive.debian.org/debian-security buster/updates main\n' > /etc/apt/sources.list
RUN apt-get -o Acquire::Check-Valid-Until=false update
RUN apt-get -y install build-essential python3-dev p7zip-full libffi-dev git binutils libproj-dev gdal-bin vim

COPY ./src .
COPY ./requirements.txt .
COPY ./dep/patch_django_py3.py .

# Copy javascript built app
COPY --from=js-build-stage /build/output /js/output

# Install required Python libraries
RUN pip install --no-cache-dir -r requirements.txt

# Workaround for GeoDjango-GEOS bug
# https://stackoverflow.com/a/18721622
RUN sed -i "s/ver = geos_version().decode()/ver = geos_version().decode().split(' ')[0]/g" /usr/local/lib/python3.9/site-packages/django/contrib/gis/geos/libgeos.py

# Patch Django 1.5 per Python 3 (html_parser.HTMLParseError e ModelBase.__classcell__)
RUN python patch_django_py3.py


# Extra temporary dependencies, to be moved to pyproject.toml
# RUN pip install django-rest-framework

# Copy Django app

EXPOSE 8000
WORKDIR /app
CMD [ "python", "manage.py", "runserver", "0.0.0.0:8000" ]