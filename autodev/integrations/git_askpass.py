#!/usr/bin/env python3
"""Noninteractive Git askpass helper; credentials come only from the publisher environment."""
import os
import sys

prompt = " ".join(sys.argv[1:]).lower()
if "username" in prompt:
    print(os.environ.get("GIT_USERNAME", "x-access-token"))
else:
    print(os.environ.get("GITHUB_TOKEN", ""))
