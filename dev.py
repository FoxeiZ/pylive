import asyncio
from functools import partial
from pathlib import Path
from threading import Thread

from flask import Flask, jsonify, redirect, request, send_from_directory
from numpy import subtract
import youtube
import ffpb


app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False
user_agent = ('firefox', 'msie', 'opera', 'chrome')

class prepare:

    __slots__ = ('playlist', 'queue', '_np')
    def __init__(self, **args):
        self.playlist = youtube.fetch_(url_playlist='https://youtube.com/playlist?list=PLtXKbXocjFKnXaucIurA63M7c5QieL7Ah')
        # self.playlist = youtube.fetch_(url_playlist='https://www.youtube.com/playlist?list=PLtXKbXocjFKmSTkRutH15wV0DCPvN1JBs')
        self.queue = []
        self._np = None

    @property
    def np(self):
        return self._np

    @np.setter
    def np(self, value):
        self._np = value

    def addqueue(self, data):
        print(f'[addqueue] {data=}')
        self.queue.append(data)

    def pop(self):
        if self.queue:
            return self.queue.pop(0)[0]
        else:
            return self.playlist.pop(0)

    async def server(self):
        print('striming server started!\n')
        proc = await asyncio.create_subprocess_exec(Path('./rtsp/rtsp-simple-server'), Path('./rtsp/rtsp-simple-server.yml'))
        await proc.wait()

    async def player(self):
        ffpb.main(['-re', '-protocol_whitelist', 'file,tls,tcp,https',
                   '-i', 'list.txt', '-c', 'copy', '-nostdin',
                   '-f', 'rtsp', 'rtsp://127.0.0.1:8554/strim'], tqdm=Handler)


audio = prepare()

class Handler:

    def __init__(self, **args):
        self.n = 0
        self.id = 2
        self.temp = None
        self.disable = False
        self.total = 17

    def close(self):
        if self.disable:
            return

        self.disable = True
        return

    def update(self, n=1):
        if self.disable:
            return

        # if self.total == self.n:
        #     print(self.temp)
        #     audio.np = self.temp

        if subtract(self.total, 10) == self.n:
            if self.id == 1:
                self.id = 2
            else:
                self.id = 1

            Path(f'audio/audio{self.id}.m4a').unlink(missing_ok=True)
            duration, self.temp = youtube.extractor(url=audio.pop(), id=self.id)
            self.total += duration
            audio.np = self.temp
            print(self.temp)

        self.n += n


@app.route('/')
def index():
    return 'owo'

@app.route('/add')
def addsong():
    url = request.args.get('url')
    try:
        audio.addqueue(youtube.checkduration(url))
        return jsonify({'result': 'success'})
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/np/')
def nowplaying():
    def makelist():
        for item in audio.queue[slice(5)]:
            yield {
                'url': item[0],
                'title': item[1]
            }
    data = audio._np
    print(audio._np)
    print(data)
    return jsonify({
        'title': data[0],
        'id': data[1],
        'original_url': data[2],
        'next': None if not audio.queue else list(makelist())
    })

@app.route('/queue/')
def getqueue():
    def makelist():
        if audio.queue:
            for item in audio.queue:
                yield {
                    'url': item[0],
                    'title': item[1]
                }
        else:
            return []

    return jsonify({'result': list(makelist())})

@app.route('/skip')
def skip():

    if not audio.queue:
        return jsonify({'error': 'queue is empty'})

    index = request.args.get('index')
    if index:
        if index < len(audio.queue):
            del audio.queue[index]
            return jsonify({'result': 'success'})
        else:
            return jsonify({'error': f'delete range must <{len(audio.queue)}'})
    else:
        del audio.queue[0]
        return jsonify({'result': 'success'})

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(Path('./'), 'favicon.ico', mimetype='image/png')


if __name__ == '__main__':

    tasks = [
        audio.server(),
        audio.player()
    ]

    async def gathers(tasks):
        results = await asyncio.gather(*tasks)
        return results

    # clean up stuff
    Path('audio/audio1.m4a').unlink(missing_ok=True)
    Path('audio/audio2.m4a').unlink(missing_ok=True)
    # Path('audio.m4a').unlink(missing_ok=True)

    # main
    partial_run = partial(app.run, host="0.0.0.0", port=9999, debug=False, use_reloader=False, threaded=True)
    t = Thread(target=partial_run)
    t.start()
    asyncio.run(gathers(tasks))
