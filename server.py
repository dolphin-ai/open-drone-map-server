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

WORK_DIR = './images'

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
        ortho_in_progress = not self.is_work_dir_empty()
        if ortho_in_progress:
            logging.info("work dir is not empty, ortho in progress")
            self.set_status(429, "orthomosaic generation already in progress, please try again")
            self.finish()
        else:
            self.finish()
            self.download_urls(req['urls'])
            self.generate_ortho(req['id'], req['uploadOrthoEndpoint'])

    def is_work_dir_empty(self):
        return len([name for name in os.listdir(WORK_DIR) if os.path.isfile(os.path.join(WORK_DIR, name))]) == 0

    def empty_work_dir(self):
        shutil.rmtree(WORK_DIR + '/*')

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
        odm_log = open("/code/logs/odm_log", "w")
        subprocess.call(
            ['python', '/code/run.py', '--opensfm-processes', '8', 'code'],
            stdout=odm_log,
            stderr=subprocess.STDOUT
        )
        file = open('./odm_orthophoto/odm_orthophoto.png', 'rb')
        files = {'file': file}
        try:
            r = requests.post(endpoint + '?id=' + str(id), files=files)
            logging.info(r.text)
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
