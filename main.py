import asyncio
from functools import partial
from pathlib import Path
from threading import Thread

from flask import Flask, jsonify, redirect, request, send_from_directory

import youtube


app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False
user_agent = ('firefox', 'msie', 'opera', 'chrome')

class prepare:

    __slots__ = ('playlist', 'queue', 'np')
    def __init__(self):
        self.playlist = youtube.fetch_(url_playlist='https://www.youtube.com/playlist?list=PLtXKbXocjFKmSTkRutH15wV0DCPvN1JBs')
        self.queue = []
        self.np = None

    def file(self, url, id):
        duration, self.np = youtube.extractor(url=url, id=id)
        # file.write(f"ffconcat version 1.0\nfile '{url}'\nfile 'list1.txt'")
        return duration-20

    def addqueue(self, url):
        print(f'[addqueue] {url=}')
        self.queue.append(url)

    def pop(self):
        if self.queue:
            return self.queue.pop(0)
        else:
            return self.playlist.pop(0)

    async def ffmpeg(self):
        await asyncio.sleep(10)
        print('ffmpeg strim started!\n')
        proc = await asyncio.create_subprocess_exec('ffmpeg', '-re', '-f', 'concat', '-safe', '0',
                                                    '-protocol_whitelist', 'file,tls,tcp,https','-i', 'list1.txt',
                                                    '-c', 'copy', '-f', 'flv', 'rtmp://127.0.0.1:1935/strim',
                                                    '-nostats', '-loglevel', 'error', '-hide_banner')
        # proc = await asyncio.create_subprocess_exec('ffmpeg', '-re', '-f', 'concat', '-safe', '0', '-i', 'list1.txt',
        #                                             '-c:a', 'aac', '-ar', '48000', '-f', 'hls', '-hls_time', '6', '-hls_list_size',
        #                                             '10', '-hls_flags', 'delete_segments', Path('./playlist/index.m3u8'), '-nostats', '-loglevel', '0', '-hide_banner')
        await proc.wait()

    async def server(self):
        print('striming server started!\n')
        proc = await asyncio.create_subprocess_exec(Path('./rtsp/rtsp-simple-server'), Path('./rtsp/rtsp-simple-server.yml'))
        await proc.wait()

    async def concat(self):
        while 1:
            await asyncio.sleep(self.file(self.pop(), 1))
            Path('audio/audio2.m4a').unlink(missing_ok=True)
            await asyncio.sleep(self.file(self.pop(), 2))
            Path('audio/audio1.m4a').unlink(missing_ok=True)


audio = prepare()


@app.route('/')
def index():
    return 'owo'


@app.route('/audio/')
def strim():
    ip = request.host.split(':')[0]
    print(ip)
    if request.user_agent.browser in user_agent:
        print('indeed browser')
        return redirect(f'http://{ip}:8000/strim')
    else:
        print('not browser')
        return redirect(f'http://{ip}:8000/strim/index.m3u8')

@app.route('/add')
def addsong():
    url = request.args.get('url')
    try:
        youtube.checkduration(url)
        audio.addqueue(url)
        return jsonify({'result': 'success'})
    except Exception as e:
        return jsonify({'error': e})

@app.route('/np')
def nowplaying():
    data = audio.np
    return jsonify({
        'title': data[0],
        'id': data[1],
        'original_url': data[2],
        'next': audio.queue[0] if audio.queue else None
    })

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(Path('./'), 'favicon.ico', mimetype='image/png')

if __name__ == '__main__':

    tasks = [
        audio.server(),
        audio.ffmpeg(),
        audio.concat()
    ]
    async def gathers(tasks):
        results = await asyncio.gather(*tasks)
        return results

    Path('audio/audio1.m4a').unlink(missing_ok=True)
    Path('audio/audio2.m4a').unlink(missing_ok=True)
    partial_run = partial(app.run, host="0.0.0.0", port=9999, debug=False, use_reloader=False, threaded=False)
    t = Thread(target=partial_run)
    t.start()
    asyncio.run(gathers(tasks))
