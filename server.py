#!/usr/bin/env python

import os
import tornado.ioloop
import tornado.web
import uuid
from tornado.options import define, options, parse_command_line
from PIL import Image
import mimetypes
import urllib2
import requests

WORK_DIR = './images'

define("port", default=5000, help="run on the given port", type=int)
define("debug", default=False, help="run in debug mode")

class RunODMHandler(tornado.web.RequestHandler):
    @tornado.web.asynchronous
    def post(self):
        urls = self.get_argument('urls', [])
        print urls
        self.download_urls(urls)
        res = self.run_odm()
        print res
        # self.write(res)
        self.finish()

    def download_urls(self, urls):
        # get the file ext
        for image_url in urls:
            res = requests.head(image_url)
            content_type = res.headers['content-type']
            ext = mimetypes.guess_extension(content_type)
            if ext == '.jpe':
                ext = '.jpg'

            # write file to disk
            filename = str(uuid.uuid4()) + ext
            filepath = os.path.join(WORK_DIR, filename)
            image_file = urllib2.urlopen(image_url)
            with open(filepath, 'wb') as output:
              output.write(image_file.read())

    def run_odm(self):
        os.system("/code/run.py --project-path /code/")
        res = { 'success': True }
        return json.dumps(res)

def main():
    parse_command_line()
    print options

    routes = [
        (r"/run", RunODMHandler),
    ]
    app = tornado.web.Application(
        routes,
        xsrf_cookies=False,
        debug=options.debug
    )
    app.listen(options.port)
    print '[server] listening on port', options.port
    tornado.ioloop.IOLoop.current().start()

if __name__ == "__main__":
    main()
