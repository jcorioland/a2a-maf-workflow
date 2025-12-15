# syntax=docker/dockerfile:1

# Microsoft Dev Containers Python base image (Python 3.12.x)
FROM mcr.microsoft.com/devcontainers/python:3.12

# Azure CLI and Terraform are installed via Dev Container Features (see devcontainer.json).

# Install uv (feature not consistently available), keep it simple via pip.
RUN python -m pip install --no-cache-dir uv
