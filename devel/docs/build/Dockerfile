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
    sphinx==1.7.0 \
    sphinx-rtd-theme \
    sphinx-autobuild \
    pygments==2.5.2 \
    mock

COPY assets/docs /docs

RUN cd "/" \
    && git clone https://github.com/AleksandarPetrov/napoleon \
    && cd /napoleon \
    && python setup.py install -f

RUN cd "/" \
    && git clone https://github.com/sphinx-contrib/restbuilder.git \
    && cd /restbuilder \
    && git checkout 8728a23fff9e841e2c2bdf72eedea14003c7169a \
    && python setup.py install -f

RUN mkdir /docs/in
RUN mkdir /docs/out
RUN mkdir /docs/rst

RUN chmod -R 777 /docs

CMD cp -r /docs/in/* /docs/source/ \
    && cd /docs \
    && sphinx-build -b html source build/html \
    && cp -r /docs/build/html/* /docs/out \
    && sphinx-build -b rst source build/rst \
    && cp -r /docs/build/rst/* /docs/rst
