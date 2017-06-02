#!/bin/bash

sudo docker run -it -p 80:5000 -v $(pwd)/images:/code/images -v $(pwd)/odm_orthophoto:/code/odm_orthophoto -v $(pwd)/odm_texturing:/code/odm_texturing dolphin-ai:odm
