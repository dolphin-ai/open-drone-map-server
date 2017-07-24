#!/usr/bin/env python

import os
import tornado.ioloop
import subprocess
import tornado.web
import uuid
from tornado.options import define, options, parse_command_line
from PIL import Image
import mimetypes
import urllib2
import requests
import json
import logging
import shutil
from shutil import copyfile
from decimal import Decimal

OPEN_SFM_PROCESSES = '16'

LOGS_DIR = 'logs'
WORK_DIR = 'images'
OUTPUT_DIR = 'jobs'
ODM_PHOTO_DIR = 'odm_orthophoto'
ODM_GEOREFERENCE_DIR = 'odm_georeferencing'
ODM_TEXTURING_DIR = 'odm_texturing'
ODM_MESHING_DIR = 'odm_meshing'
OPENSFM_DIR = 'opensfm'

define("port", default=80, help="run on the given port", type=int)
define("debug", default=False, help="run in debug mode")

def is_work_dir_empty():
    if not os.path.exists(WORK_DIR):
        os.makedirs(WORK_DIR)
    return len([name for name in os.listdir(WORK_DIR) if os.path.isfile(os.path.join(WORK_DIR, name))]) == 0

def ortho_job_complete(job_id):
    filepath = ortho_image_path_for_job_id(job_id)
    return os.path.isfile(filepath)

def ortho_image_path_for_job_id(job_id):
    job_id = str(job_id)
    job_dir = get_job_output_dir(job_id)
    return os.path.join(job_dir, 'odm_orthophoto.png')

def empty_work_dir():
    logging.info('Emptying work dirs')
    empty_dir(WORK_DIR)
    empty_odm_dirs()

def empty_odm_dirs():
    empty_dir(ODM_PHOTO_DIR)

def empty_all_odm_output_dirs():
    empty_dir(ODM_GEOREFERENCE_DIR)
    empty_dir(ODM_TEXTURING_DIR)
    empty_dir(ODM_MESHING_DIR)
    empty_dir(OPENSFM_DIR)

def empty_dir(dir):
    for f in os.listdir(dir):
        fp = os.path.join(dir, f)
        if os.path.isfile(fp):
            os.remove(fp)

def get_job_output_dir(id):
    dir = os.path.join(OUTPUT_DIR, str(id))
    if not os.path.exists(dir):
        os.makedirs(dir)
    return dir

def ortho_process_succeeded():
    return os.path.isfile(os.path.join(ODM_PHOTO_DIR, 'odm_orthophoto.png'))

def utm_coords_filepath(job_id):
    job_dir = get_job_output_dir(str(job_id))
    return os.path.join(job_dir, 'odm_georeferencing_model_geo.txt')

def utm_corners_filepath(job_id):
    job_dir = get_job_output_dir(str(job_id))
    return os.path.join(job_dir, 'odm_orthophoto_corners.txt')

def parse_utm_coords(job_id):
    utm = {}

    with open(utm_coords_filepath(job_id), 'rb') as f:
     for i, line in enumerate(f):
         if i == 1:
            coords = line.split()
            utm['east'] = Decimal(coords[0])
            utm['north'] = Decimal(coords[1])

    with open(utm_corners_filepath(job_id), 'rb') as f:
     for i, line in enumerate(f):
         if i == 0:
            corners = line.split()
            utm['xMin'] = utm['east'] + Decimal(corners[0])
            utm['yMin'] = utm['north'] + Decimal(corners[1])
            utm['xMax'] = utm['east'] + Decimal(corners[2])
            utm['yMax'] = utm['north'] + Decimal(corners[3])

    return utm

def send_generated_ortho_to_requester(id, endpoint, image_path):
    utm = parse_utm_coords(id)
    file = open(image_path, 'rb')
    files = {'file': file}
    logging.info('Sending %s for job %s to %s', image_path, id, endpoint)
    try:
        query_string = '?id=%s&utmEast=%s&utmNorth=%s&utmXMin=%s&utmXMax=%s&utmYMin=%s&utmYMax=%s' % (
            id,
            utm['east'],
            utm['north'],
            utm['xMin'],
            utm['xMax'],
            utm['yMin'],
            utm['yMax'],
        )
        r = requests.post(endpoint + query_string, files=files)
        logging.info(r.text)
    except:
        logging.info('[job %s] Unable to complete callback (%s)', id, endpoint)
    finally:
        file.close()
        empty_work_dir()

def send_error_message_to_requester(id, endpoint):
    try:
        r = requests.post(endpoint + '?id=' + id + '&error=true', files={})
        logging.info(r.text)
    except:
        logging.info('exception caught')

class HealthCheckHandler(tornado.web.RequestHandler):
    @tornado.web.asynchronous
    def get(self):
        self.finish()

class RunJobCallbackHandler(tornado.web.RequestHandler):
    @tornado.web.asynchronous
    def post(self):
        req = json.loads(self.request.body)

        job_id = str(req['id'])
        endpoint = str(req['uploadOrthoEndpoint'])

        if ortho_job_complete(job_id):
            ortho_image_path = ortho_image_path_for_job_id(job_id)
            send_generated_ortho_to_requester(job_id, endpoint, ortho_image_path)
            self.finish()
            return

        self.finish()

class RunOpenDroneMapHandler(tornado.web.RequestHandler):
    @tornado.web.asynchronous
    def post(self):
        req = json.loads(self.request.body)

        job_id = str(req['id'])
        images = req['images']
        endpoint = str(req['uploadOrthoEndpoint'])

        ortho_in_progress = not is_work_dir_empty()
        if ortho_in_progress:
            logging.info("> work dir is not empty, ortho in progress")
            self.set_status(429, "orthomosaic generation already in progress, please try again")
            self.finish()
            return

        self.finish()
        empty_odm_dirs()
        empty_all_odm_output_dirs()
        self.download_images(images)
        self.generate_ortho(job_id, endpoint)

    def download_images(self, images):
        if images is None:
            return

        for image in images:
            image_url = image['url']
            logging.info("downloading %s", image_url)
            res = requests.head(image_url)
            filepath = os.path.join(WORK_DIR, image['filename'])
            image_file = urllib2.urlopen(image_url)
            with open(filepath, 'wb') as output:
              output.write(image_file.read())

    def generate_ortho(self, id, endpoint):
        id = str(id)
        odm_log = open("logs/odm_log", "w")
        images_path = '%s/images:/code/images' % (os.getcwd())
        opensfm_path = '%s/opensfm:/code/opensfm' % (os.getcwd())
        meshing_path = '%s/odm_meshing:/code/odm_meshing' % (os.getcwd())
        texturing_path = '%s/odm_texturing:/code/odm_texturing' % (os.getcwd())
        georeferencing_path = '%s/odm_georeferencing:/code/odm_georeferencing' % (os.getcwd())
        orthophoto_path = '%s/odm_orthophoto:/code/odm_orthophoto' % (os.getcwd())
        subprocess.call([
            'sudo', 'docker', 'run', '-i', '--rm',
            '-v', images_path,
            '-v', opensfm_path,
            '-v', meshing_path,
            '-v', texturing_path,
            '-v', georeferencing_path,
            '-v', orthophoto_path,
            'opendronemap/opendronemap',
            '--opensfm-processes', OPEN_SFM_PROCESSES
            ],
            stdout=odm_log,
            stderr=subprocess.STDOUT
        )
        if ortho_process_succeeded():
            logging.info('[job %s] ortho generation complete', id)

            ortho_image_path = ortho_image_path_for_job_id(id)
            copyfile(os.path.join(ODM_PHOTO_DIR, 'odm_orthophoto.png'), ortho_image_path)

            utm_coords_fp = utm_coords_filepath(id)
            copyfile(os.path.join(ODM_GEOREFERENCE_DIR, 'odm_georeferencing_model_geo.txt'), utm_coords_fp)

            utm_corners_fp = utm_corners_filepath(id)
            copyfile(os.path.join(ODM_PHOTO_DIR, 'odm_orthophoto_corners.txt'), utm_corners_fp)

            send_generated_ortho_to_requester(id, endpoint, ortho_image_path)
        else:
            logging.info('[job %s] ortho generation failed, see logs/odm_log', id)
            send_error_message_to_requester(id, endpoint)
            empty_work_dir()

def main():
    parse_command_line()

    if not os.path.exists(WORK_DIR):
        os.makedirs(WORK_DIR)

    if not os.path.exists(LOGS_DIR):
        os.makedirs(LOGS_DIR)

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    if not os.path.exists(ODM_PHOTO_DIR):
        os.makedirs(ODM_PHOTO_DIR)

    for dir in ['opensfm', 'odm_meshing', 'odm_texturing', 'odm_georeferencing']:
        if not os.path.exists(dir):
            os.makedirs(dir)

    routes = [
        (r"/", HealthCheckHandler),
        (r"/run", RunOpenDroneMapHandler),
        (r"/job", RunJobCallbackHandler),
    ]
    app = tornado.web.Application(
        routes,
        xsrf_cookies=False,
        debug=options.debug
    )
    app.listen(options.port)
    logging.info('[server] listening on port %d', options.port)
    tornado.ioloop.IOLoop.current().start()

if __name__ == "__main__":
    main()
