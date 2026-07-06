#!/usr/bin/env python3
import re, sys, pathlib
req = set(l.strip() for l in open('requirements.txt') if l.strip())
docker = open('Dockerfile').read()
m = re.search(r'pip3 install ([^\n]+?) --break-system-packages', docker)
pip_pkgs = set(p for p in m.group(1).split() if p) if m else set()
extra_in_docker = pip_pkgs - req
print("requirements.txt:", sorted(req))
print("Dockerfile pip:", sorted(pip_pkgs))
print("В Dockerfile, но не в requirements.txt:", sorted(extra_in_docker))
sys.exit(0 if not extra_in_docker else 1)