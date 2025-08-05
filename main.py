import json

from flask import Flask, Response, abort, jsonify, render_template, request

from src.general import URLRequest, run_in_thread
from src.server import QueueAudioHandler

WEBHOOK_URL = None
app = Flask(__name__, static_url_path="/static")
prev_add = None

# audio streaming
audio = QueueAudioHandler()


def send_webhook(func):
    def webhook(response: Response, webhook_url=None, func_name=""):
        if not webhook_url:
            return

        res = URLRequest.request(
            webhook_url,
            method="POST",
            data={
                "content": f"`/{func_name}`\n```{json.dumps(response.json, indent=2)}\n```",
                "username": "debug radio",
            },
            headers={
                "Content-Type": "application/json",
            },
        )

        if res.getcode() != 204:
            print("Failed to send webhook")
            print(res.read().decode("utf-8"))

    def wrapper(*args, **kwargs):
        ret = func(*args, **kwargs)
        run_in_thread(
            webhook,
            wait_for_result=False,
            response=ret[0],
            func_name=func.__name__,
            webhook_url=WEBHOOK_URL,
        )
        return ret

    wrapper.__name__ = func.__name__
    return wrapper


def check_empty(arg) -> bool:
    if arg is None:
        return True

    return any(arg) and (len(arg) != 0)


def make_response(
    data=None,
    msg: str = "success",
    is_error: bool = False,
    status_code: int = 200,
    other_data=None,
) -> tuple[Response, int]:
    build_resp = {
        "msg": msg,
        "error": is_error,
        "data": data if check_empty(data) else None,
    }

    if other_data:
        build_resp.update({"other_data": other_data})

    return jsonify(build_resp), status_code


def make_error(*args, **kwargs):
    return make_response(*args, is_error=True, **kwargs)


def gen(audio: QueueAudioHandler):
    yield audio.wait_for_header()
    while audio._audio_thread.is_alive():
        yield audio.buffer
        audio.event.wait()
    return


def check_args(args_name: list):
    def decorator(func):
        def wrapper(*args, **kwargs):
            if request.method == "GET":
                data = request.args
            elif request.method == "POST":
                if request.is_json:
                    data = request.json
                else:
                    data = request.form
            else:
                return abort(500)

            for arg in args_name:
                if arg not in data:
                    return abort(500)
                else:
                    kwargs[arg] = data.get(arg)
            return func(*args, **kwargs)

        wrapper.__name__ = func.__name__
        return wrapper

    return decorator


def check_ratelimit(func):
    def wrapper(*args, **kwargs):
        global prev_add
        if prev_add == request.remote_addr:
            return make_error(msg="Calm down you just use this.", status_code=429)
        prev_add = request.remote_addr
        return func(*args, **kwargs)

    wrapper.__name__ = func.__name__
    return wrapper


@app.route("/add", methods=["POST"])
@check_args(["url"])
def add(url):
    try:
        audio.add(url)
    except Exception as err:
        return make_error(msg=f"{err.__class__.__name__}: {str(err)}")

    return make_response()


@app.route("/queue")
def get_queue():
    index = int(request.args.get("index") or request.args.get("page", 0)) + 1
    use_autoqueue = request.args.get("use_autoqueue", "0") == "1"

    end_offset = max(index * 5, len(audio.queue))
    start_offset = max(end_offset - 5, 0)

    data = {
        "queue": audio.queue[start_offset:end_offset],
    }

    if use_autoqueue and audio.auto_queue:
        data.update({"auto_queue": audio.auto_queue})

    return make_response(data=data)


@app.route("/np")
@app.route("/nowplaying")
def get_nowplaying():
    data: dict = {"now_playing": audio.now_playing}

    if audio.queue:
        data.update({"next_up": audio.queue[0]})

    return make_response(data=data)


@app.route("/skip", methods=["POST"])
def skip():
    audio._skip = True
    return make_response()


@app.route("/stream")
def get_stream():
    if not audio.ffmpeg:
        return make_response(msg="No stream avaliable.", is_error=True, status_code=404)

    return Response(gen(audio), content_type="audio/ogg", status=200)


@app.route("/")
def index():
    return render_template("stream.html", np=audio.now_playing, queue=audio.queue)


@app.route("/watch_event")
def watch_event():
    return Response(audio.event_queue.watch(), content_type="text/event-stream")


if __name__ == "__main__":
    app.run("0.0.0.0", port=5000, threaded=True)
