#!/bin/bash

set -eu

IMAGE=build-zlib
podman build . -t $IMAGE --build-arg uid=$UID
