#! /bin/bash
wget https://download.docker.com/linux/ubuntu/dists/zesty/pool/edge/amd64/docker-ce_17.05.0~ce-0~ubuntu-zesty_amd64.deb
sudo dpkg -i docker-ce_17.05.0~ce-0~ubuntu-zesty_amd64.deb
git clone https://github.com/dolphin-ai/open-drone-map-server.git
cd open-drone-map-server
sudo docker build -t dolphin-ai:odm .
