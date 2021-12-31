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

    """
    Return data as follow:
        - duration[float]
        - [tuple]:
            - title[str]
            - id[str]
            - original_url[str]
    """

    ytdlopts = globopt.copy()
    ytdlopts.update({
        'format': 'bestaudio[ext=m4a]/bestaudio/best',
        'outtmpl': f'audio/audio{id}.%(ext)s',
        'restrictfilenames': True,
    })

    with YoutubeDL(ytdlopts) as ytdl:
        try:
            data = ytdl.extract_info(url=url, download=True)
            print(data['title'])
            return (data['duration'], (data['title'], data['id'], data['original_url']))
        except DownloadError:
            print('403 link forbidden but i dont fucking care')
            pass

def fetch_(url_playlist):
    playlist = []
    with YoutubeDL(globopt) as ytdl:
        data = ytdl.extract_info(url=url_playlist, download=False, process=False)
        for item in data['entries']:
            if item['duration'] <= 600.0:
                playlist.append(item['url'])
    shuffle(playlist)
    return playlist

def checkduration(url):
    """
    Return a tuple include:
        - url[str]
        - title[str]
    """
    with YoutubeDL(globopt) as ytdl:
        data = ytdl.extract_info(url=url, download=False, process=False)
        if data['duration'] <= 600.0: #10 mins
            return (data['original_url'], data['title'])
        else:
            raise Exception('duration must <10min')
