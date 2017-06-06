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
from shutil import copyfile

OPEN_SFM_PROCESSES = '8'

WORK_DIR = '/code/images'
OUTPUT_DIR = '/code/jobs'
ODM_PHOTO_DIR = '/code/odm_orthophoto'
ODM_TEXTURE_DIR = '/code/odm_texturing'

define("port", default=5000, help="run on the given port", type=int)
define("debug", default=False, help="run in debug mode")

class HealthCheckHandler(tornado.web.RequestHandler):
    @tornado.web.asynchronous
    def get(self):
        self.finish()

class RunOpenDroneMapHandler(tornado.web.RequestHandler):
    @tornado.web.asynchronous
    def post(self):
        req = json.loads(self.request.body)

        job_id = str(req['id'])
        image_urls = req['urls']
        endpoint = str(req['uploadOrthoEndpoint'])

        if self.ortho_job_complete(job_id):
            ortho_image_path = self.ortho_image_path_for_job_id(job_id)
            self.send_generated_ortho_to_requester(job_id, endpoint, ortho_image_path)
            self.finish()
            return

        ortho_in_progress = not self.is_work_dir_empty()
        if ortho_in_progress:
            logging.info("work dir is not empty, ortho in progress")
            self.set_status(429, "orthomosaic generation already in progress, please try again")
            self.finish()
            return

        self.finish()
        self.empty_odm_dirs()
        self.download_urls(image_urls)
        self.generate_ortho(job_id, endpoint)

    def is_work_dir_empty(self):
        return len([name for name in os.listdir(WORK_DIR) if os.path.isfile(os.path.join(WORK_DIR, name))]) == 0

    def ortho_job_complete(self, job_id):
        filepath = self.ortho_image_path_for_job_id(job_id)
        print 'filepath: ', filepath
        return os.path.isfile(filepath)

    def ortho_image_path_for_job_id(self, job_id):
        job_id = str(job_id)
        job_dir = self.get_job_output_dir(job_id)
        return os.path.join(job_dir, 'odm_orthophoto.png')

    def empty_work_dir(self):
        logging.info('Emptying work dirs')
        self.empty_dir(WORK_DIR)
        self.empty_odm_dirs()

    def empty_odm_dirs(self):
        self.empty_dir(ODM_PHOTO_DIR)
        self.empty_dir(ODM_TEXTURE_DIR)

    def empty_dir(self, dir):
        for f in os.listdir(dir):
            os.remove(os.path.join(dir, f))

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
        odm_log = open("/code/logs/odm_log", "w")
        subprocess.call(
            ['python', '/code/run.py', '--opensfm-processes', OPEN_SFM_PROCESSES, 'code'],
            stdout=odm_log,
            stderr=subprocess.STDOUT
        )
        job_dir = self.get_job_output_dir(id)
        ortho_image_path = os.path.join(job_dir, 'odm_orthophoto.png')
        copyfile('./odm_orthophoto/odm_orthophoto.png', ortho_image_path)
        self.send_generated_ortho_to_requester(id, endpoint, ortho_image_pathjob_dir)

    def get_job_output_dir(self, id):
        dir = os.path.join(OUTPUT_DIR, str(id))
        if not os.path.exists(dir):
            os.makedirs(dir)
        return dir

    def send_generated_ortho_to_requester(self, id, endpoint, image_path):
        file = open(image_path, 'rb')
        files = {'file': file}
        logging.info('Sending %s for project %s to %s', image_path, id, endpoint)
        try:
            r = requests.post(endpoint + '?id=' + id, files=files)
            logging.info(r.text)
        except:
            logging.info('exception caught')
        finally:
            file.close()
            self.empty_work_dir()

def main():
    parse_command_line()

    routes = [
        (r"/", HealthCheckHandler),
        (r"/run", RunOpenDroneMapHandler),
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
