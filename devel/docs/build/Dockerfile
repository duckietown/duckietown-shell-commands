ARG BASE_IMAGE
FROM ${BASE_IMAGE}

ARG BOOK_NAME
ENV BOOK_NAME "${BOOK_NAME}"
RUN echo "Building book: ${BOOK_NAME}"

# environment
ENV DISABLE_CONTRACTS 1

# install apt dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install \
    sphinx~=3.2.0 \
    sphinx-rtd-theme \
    sphinx-autobuild \
    pygments==2.5.2 \
    mock

COPY assets/docs /docs

RUN cd "/" \
    && git clone https://github.com/AleksandarPetrov/napoleon \
    && cd /napoleon \
    && python3 setup.py install -f

RUN mkdir -p /docs/in
RUN mkdir -p /${BOOK_NAME}
RUN mkdir -p /out

COPY assets/output-html.manifest.yaml /out

RUN chmod -R 777 /docs

CMD cp -r /docs/in/* /docs/source/ \
    && cd /docs \
    && sphinx-build -b html source build/html \
    && cp -r /docs/build/html/* /${BOOK_NAME}/ \
    && cp /out/output-html.manifest.yaml /${BOOK_NAME}/ \
    || cat /tmp/sphinx-err-*.log
