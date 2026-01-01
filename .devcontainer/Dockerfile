# Development Dockerfile for cmdorc
# For use with VS Code Remote Development

FROM python:3.12-slim AS base

# Prevent apt from prompting for input
ENV DEBIAN_FRONTEND=noninteractive

# Install essential packages
RUN apt-get update && apt-get install -y \
    curl \
    git \
    npm \
    sudo \
    tree \
    vim \
    && rm -rf /var/lib/apt/lists/*

# Create the developer user and set up permissions
RUN useradd -s /bin/bash -m developer && \
    usermod -aG sudo developer && \
    echo "developer ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers

# Add claude code globally
RUN npm install -g @anthropic-ai/claude-code

# Install Language Servers (as root, globally available)
# Python LSP
RUN pip install --no-cache-dir pyright

# TypeScript/JavaScript LSP
RUN npm install -g @vtsls/language-server typescript

# Enable LSP tool for claude code
ENV ENABLE_LSP_TOOL=1

# Switch to developer user for remaining operations
USER developer

# Set up Python environment
ENV PATH=/home/developer/.local/bin:$PATH
WORKDIR /mounted/dev/cmdorc

# Install Python packages
RUN python -m ensurepip --default-pip && \
    pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir pdm

RUN pip install --no-cache-dir \
    build \
    GitPython \
    pdm \
    pydantic \
    prepdir \
    pytest \
    ruff \
    twine

RUN git config --global --add safe.directory /mounted/dev/cmdorc