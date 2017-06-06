#! /bin/sh
cd /home/nicholashughes/open-drone-map-server
git pull
sudo docker build -t dolphin-ai:odm .
sudo docker run -i -p 80:5000 \
  -v log:log \
  -v odm_log:odm_log \
  -v $(pwd)/images:/code/images \
  -v $(pwd)/odm_orthophoto:/code/odm_orthophoto \
  -v $(pwd)/odm_texturing:/code/odm_texturing \
  dolphin-ai:odm
