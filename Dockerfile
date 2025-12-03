FROM ubuntu:22.04

RUN apt update -y \
    && apt install --no-install-recommends -y \
        autoconf \
        automake \
        libtool \
        autopoint \
        bison \
        curl \
        gettext \
        git \
        gperf \
        texinfo \
        patch \
        rsync \
        xz-utils \
        gcc \
        g++ \
        clang-14 \
        llvm-14 \
        llvm-14-dev \
        llvm-14-tools \
        bear \
        libclang-cpp14 \
        libllvm14 \
        build-essential \
        libc6-dev \
        binutils \
        make \
        wget \
        ca-certificates \
        python3 \
    && rm -rf /var/lib/apt/lists/*

# -------------------------
# Build zlib
# -------------------------
COPY zlib/ /zlib
WORKDIR /zlib
RUN ./configure --prefix=/usr && \
    make -j$(nproc) && \
    make install

# -------------------------
# Setup Unity
# -------------------------
WORKDIR /zlib/unity
RUN curl -LO https://raw.githubusercontent.com/ThrowTheSwitch/Unity/refs/heads/master/src/unity.c \
    && curl -LO https://raw.githubusercontent.com/ThrowTheSwitch/Unity/refs/heads/master/src/unity.h \
    && curl -LO https://raw.githubusercontent.com/ThrowTheSwitch/Unity/refs/heads/master/src/unity_internals.h

# Weak setUp/tearDown to avoid linker errors
RUN echo "\n__attribute__((weak)) void setUp(void) {}\n" >> unity.c
RUN echo "__attribute__((weak)) void tearDown(void) {}\n" >> unity.c

# Compile Unity object
RUN gcc -c -fPIC -o unity.o unity.c -I.

# Patch zlib Makefile for tests
COPY patch_makefile.py /zlib/
WORKDIR /zlib
RUN python3 patch_makefile.py

# Install Mull 14 (for LLVM 14)
RUN wget https://github.com/mull-project/mull/releases/download/0.26.1/Mull-14-0.26.1-LLVM-14.0-ubuntu-x86_64-22.04.deb -O /tmp/mull.deb && \
    apt-get install -y /tmp/mull.deb && rm /tmp/mull.deb

WORKDIR /zlib
RUN make -j$(nproc) check
# -------------------------
# Container default
# -------------------------
CMD ["/bin/bash"]