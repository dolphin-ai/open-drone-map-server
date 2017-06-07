#! /bin/sh
cd /home/nicholashughes/open-drone-map-server
sudo rm -rf $(pwd)/images $(pwd)/odm_orthophoto
sudo git fetch --all && sudo git reset --hard origin/master
sudo pip install --user -r requirements.txt
sudo python server.py --port=80 >> logs/log 2>&1
