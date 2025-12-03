FROM ubuntu:24.04

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
WORKDIR /unity
RUN curl -LO https://raw.githubusercontent.com/ThrowTheSwitch/Unity/refs/heads/master/src/unity.c \
    && curl -LO https://raw.githubusercontent.com/ThrowTheSwitch/Unity/refs/heads/master/src/unity.h \
    && curl -LO https://raw.githubusercontent.com/ThrowTheSwitch/Unity/refs/heads/master/src/unity_internals.h

# Weak setUp/tearDown to avoid linker errors
RUN echo "\n__attribute__((weak)) void setUp(void) {}\n" >> unity.c
RUN echo "__attribute__((weak)) void tearDown(void) {}\n" >> unity.c

# Compile Unity object
RUN gcc -c -fPIC -o unity.o unity.c -I.

# Copy Unity headers into zlib source dir so Makefile can find them
RUN cp unity.h unity_internals.h /zlib/

# -------------------------
# Trick: allow make to automatically link Unity in tests
# -------------------------
# Zlib's Makefile does not know Unity, so we create a dummy Makefile variable
# and inject unity.o into the link step
WORKDIR /zlib
RUN make -j$(nproc) check
# -------------------------
# Container default
# -------------------------
CMD ["/bin/bash"]