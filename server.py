#!/usr/bin/env python

import os
import sys
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
from shutil import rmtree
from decimal import Decimal
import cv2
import math
import numpy as np

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

STATE_READY = 'ready'
STATE_WORKING = 'working'
__current_state = STATE_READY

def ready():
    return __current_state == STATE_READY

def busy():
    return __current_state == STATE_WORKING

def set_state(state):
    current_state = state

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
        else:
            rmtree(fp)

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

def reconstruction_json_filepath(job_id):
    job_dir = get_job_output_dir(str(job_id))
    return os.path.join(job_dir, 'reconstruction.json')

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
        logging.info("[job %s] unexpected error: %s", id, str(sys.exc_info()[0]))
        logging.info('[job %s] unable to complete callback (%s)', id, endpoint)
    finally:
        file.close()
        empty_work_dir()

def send_source_image_rotations_to_requester(id, endpoint):
    output = {}

    with open(reconstruction_json_filepath(id), 'rb') as f:
        reconstruction = json.load(f)
        shots = reconstruction[0]['shots']
        for filename, shot in shots.iteritems():
            print filename
            rot = shot['rotation']
            rot_matrix = cv2.Rodrigues(np.array(shot['rotation']))[0]
            euler_angles = rotation_matrix_to_euler_angles(rot_matrix)
            shot['euler_rotation'] = euler_angles.tolist()
            output[filename] = shot

    with open(reconstruction_json_filepath(id), 'w') as outfile:
        json.dump(output, outfile)

    fp = reconstruction_json_filepath(id)
    file = open(fp, 'rb')
    logging.info('[job %s] sending %s to %s', id, fp, endpoint)
    print('[job %s] sending %s to %s', id, fp, endpoint)

    try:
        query_string = '?id=%s' % (id)
        r = requests.post(endpoint + query_string, data=file)
        logging.info(r.text)
        print(r.text)
    except:
        logging.info("[job %s] unexpected error: %s", id, str(sys.exc_info()[0]))
        logging.info('[job %s] unable to complete metadata callback (%s)', id, endpoint)
        print('[job %s] unable to complete metadata callback (%s)', id, endpoint)
    finally:
        file.close()

def rotation_matrix_to_euler_angles(rot):
    sy = math.sqrt(rot[0,0] * rot[0,0] +  rot[1,0] * rot[1,0])
    singular = sy < 1e-6

    if not singular:
        x = math.atan2(rot[2,1] , rot[2,2])
        y = math.atan2(-rot[2,0], sy)
        z = math.atan2(rot[1,0], rot[0,0])
    else:
        x = math.atan2(-rot[1,2], rot[1,1])
        y = math.atan2(-rot[2,0], sy)
        z = 0

    return np.array([x, y, z])

def send_error_message_to_requester(id, endpoint):
    try:
        r = requests.post(endpoint + '?id=' + id + '&error=true', files={})
        logging.info(r.text)
    except:
        logging.info("[job %s] unexpected error: %s", str(id), str(sys.exc_info()[0]))
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
        upload_endpoint = str(req['uploadOrthoEndpoint'])
        metadata_endpoint = str(req['uploadMetadataEndpoint'])

        if ortho_job_complete(job_id):
            ortho_image_path = ortho_image_path_for_job_id(job_id)
            send_generated_ortho_to_requester(job_id, upload_endpoint, ortho_image_path)
            send_source_image_rotations_to_requester(job_id, metadata_endpoint)
            self.finish()
            return

        self.finish()

class RunOpenDroneMapHandler(tornado.web.RequestHandler):
    @tornado.web.asynchronous
    def post(self):
        req = json.loads(self.request.body)

        job_id = str(req['id'])
        images = req['images']
        upload_endpoint = str(req['uploadOrthoEndpoint'])
        metadata_endpoint = str(req['uploadMetadataEndpoint'])

        if busy():
            logging.info("> ortho job already in progress")
            self.set_status(429, "orthomosaic generation already in progress, please try again")
            self.finish()
            return

        self.finish()

        set_state(STATE_WORKING)
        empty_odm_dirs()
        empty_all_odm_output_dirs()
        self.download_images(images)
        self.generate_ortho(job_id, upload_endpoint, metadata_endpoint)

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

    def generate_ortho(self, id, upload_endpoint, metadata_endpoint):
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

        try:
            if ortho_process_succeeded():
                logging.info('[job %s] ortho generation complete', id)

                ortho_image_path = ortho_image_path_for_job_id(id)
                copyfile(os.path.join(ODM_PHOTO_DIR, 'odm_orthophoto.png'), ortho_image_path)

                utm_coords_fp = utm_coords_filepath(id)
                copyfile(os.path.join(ODM_GEOREFERENCE_DIR, 'odm_georeferencing_model_geo.txt'), utm_coords_fp)

                utm_corners_fp = utm_corners_filepath(id)
                copyfile(os.path.join(ODM_PHOTO_DIR, 'odm_orthophoto_corners.txt'), utm_corners_fp)

                reconstruction_json_fp = reconstruction_json_filepath(id)
                copyfile(os.path.join(OPENSFM_DIR, 'reconstruction.json'), reconstruction_json_fp)

                send_generated_ortho_to_requester(id, upload_endpoint, ortho_image_path)
                send_source_image_rotations_to_requester(id, metadata_endpoint)
            else:
                logging.info('[job %s] ortho generation failed, see logs/odm_log', id)
                send_error_message_to_requester(id, upload_endpoint)
                empty_work_dir()

        except:
            logging.info("[job %s] unexpected error: %s", id, str(sys.exc_info()[0]))

        finally:
            set_state(STATE_READY)

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
