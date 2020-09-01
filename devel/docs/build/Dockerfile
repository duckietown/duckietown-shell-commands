ARG BASE_IMAGE
FROM ${BASE_IMAGE}

# environment
ENV DISABLE_CONTRACTS 1

# install apt dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install \
    sphinx==1.8.5 \
    sphinx-rtd-theme \
    sphinx-autobuild \
    pygments==2.5.2 \
    mock

COPY assets/docs /docs

RUN cd "/" \
    && git clone https://github.com/AleksandarPetrov/napoleon \
    && cd /napoleon \
    && python setup.py install -f

RUN mkdir /docs/in
RUN mkdir /docs/out
RUN mkdir -p /sphinx_docs/out

COPY assets/output-html.manifest.yaml /sphinx_docs/out

RUN chmod -R 777 /docs

CMD cp -r /docs/in/* /docs/source/ \
    && cd /docs \
    && sphinx-build -b html source build/html \
    && cp -r /docs/build/html/* /docs/out \
    && cp -r /docs/build/html/* /sphinx_docs/out \
    && tar --create --verbose --file=/docs/out/package.tgz  /sphinx_docs/out/* \
    || cat /tmp/sphinx-err-*.log
