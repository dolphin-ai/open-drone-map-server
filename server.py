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

OPEN_SFM_PROCESSES = '8'

LOGS_DIR = 'logs'
WORK_DIR = 'images'
OUTPUT_DIR = 'jobs'
ODM_PHOTO_DIR = 'odm_orthophoto'

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

def empty_dir(dir):
    for f in os.listdir(dir):
        os.remove(os.path.join(dir, f))

def get_job_output_dir(id):
    dir = os.path.join(OUTPUT_DIR, str(id))
    if not os.path.exists(dir):
        os.makedirs(dir)
    return dir

def ortho_process_succeeded():
    return os.path.isfile(os.path.join(ODM_PHOTO_DIR, 'odm_orthophoto.png'))

def send_generated_ortho_to_requester(id, endpoint, image_path):
    file = open(image_path, 'rb')
    files = {'file': file}
    logging.info('Sending %s for project %s to %s', image_path, id, endpoint)
    try:
        r = requests.post(endpoint + '?id=' + id, files=files)
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
        image_urls = req['urls']
        endpoint = str(req['uploadOrthoEndpoint'])

        if ortho_job_complete(job_id):
            ortho_image_path = ortho_image_path_for_job_id(job_id)
            send_generated_ortho_to_requester(job_id, endpoint, ortho_image_path)
            self.finish()
            return

        ortho_in_progress = not is_work_dir_empty()
        if ortho_in_progress:
            logging.info("> work dir is not empty, ortho in progress")
            self.set_status(429, "orthomosaic generation already in progress, please try again")
            self.finish()
            return

        self.finish()
        empty_odm_dirs()
        self.download_urls(image_urls)
        self.generate_ortho(job_id, endpoint)

    def download_urls(self, urls):
        for image_url in urls:
            logging.info("downloading %s", image_url)
            res = requests.head(image_url)
            content_type = res.headers['content-type']
            ext = mimetypes.guess_extension(content_type)
            if ext == '.jpe':
                ext = '.jpg'

            filename = str(uuid.uuid4()) + ext
            filepath = os.path.join(WORK_DIR, filename)
            image_file = urllib2.urlopen(image_url)
            with open(filepath, 'wb') as output:
              output.write(image_file.read())

    def generate_ortho(self, id, endpoint):
        id = str(id)
        odm_log = open("logs/odm_log", "w")
        images_path= '%s/images:/code/images' % (os.getcwd())
        output_path= '%s/odm_orthophoto:/code/odm_orthophoto' % (os.getcwd())
        subprocess.call([
            'sudo', 'docker', 'run', '-i', '--rm',
            '-v', images_path,
            '-v', output_path,
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
