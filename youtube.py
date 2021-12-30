from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError
from random import shuffle

globopt = {
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'logtostderr': False,
        'quiet': True,
        'no_warnings': True,
        'source_address': '0.0.0.0'
}

def extractor(url, id):

    ytdlopts = {
        'format': 'bestaudio[ext=m4a]',
        'outtmpl': f'audio/audio{id}.%(ext)s',
        'restrictfilenames': True,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'logtostderr': False,
        'quiet': True,
        'no_warnings': True,
        'default_search': 'auto',
        'source_address': '0.0.0.0'  # ipv6 addresses cause issues sometimes
    }

    with YoutubeDL(ytdlopts) as ytdl:
        try:
            data = ytdl.extract_info(url=url, download=True)
            print(data['title'])
            return int(data['duration'])
        except DownloadError:
            print('403 link forbidden but i dont fucking care')
            pass

def fetch_(url_playlist):
    playlist = []
    with YoutubeDL(globopt) as ytdl:
        data = ytdl.extract_info(url=url_playlist, download=False, process=False)
        for i in data['entries']:
            playlist.append(i['url'])
    shuffle(playlist)
    return playlist

def checkduration(url):
    with YoutubeDL(globopt) as ytdl:
        data = ytdl.extract_info(url=url, download=False, process=False)
        if data['duration'] <= 600.0: #10 mins
            return True
        else:
            return False
