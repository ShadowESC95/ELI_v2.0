from eli.execution import router_enhanced as router


def _route(text: str) -> dict:
    fn = getattr(router, "route_command", None) or getattr(router, "route", None)
    assert callable(fn), "router has no route_command/route callable"
    out = fn(text)
    assert isinstance(out, dict), f"router returned non-dict for {text!r}: {out!r}"
    assert "action" in out, f"router output missing action for {text!r}: {out!r}"
    return out


def _assert_action(text: str, action: str):
    out = _route(text)
    assert out["action"] == action, f"{text!r} -> {out!r}"
    return out


def _assert_arg(text: str, key: str, expected):
    out = _route(text)
    args = out.get("args") or {}
    assert args.get(key) == expected, f"{text!r} expected args[{key!r}]={expected!r}, got {out!r}"
    return out


def test_direct_media_controls_do_not_need_wake_word():
    _assert_action("pause", "PAUSE_MEDIA")
    _assert_action("resume", "PLAY_MEDIA")
    _assert_action("next", "NEXT_MEDIA")
    _assert_action("previous", "PREVIOUS_MEDIA")
    _assert_action("volume up", "VOLUME")
    _assert_action("volume down", "VOLUME")


def test_bare_or_incomplete_play_does_not_launch_garbage():
    """
    Lock the important behaviour:
    incomplete play/media phrases must NOT launch garbage media.

    The exact user-facing NOOP wording may come from either the media
    normalizer or the voice/fuzzy incomplete-command path.
    """
    for text in ["play", "play the", "play the watcher by", "play ghetto gospel on"]:
        out = _route(text)
        assert out["action"] == "NOOP"

        args = out.get("args") or {}
        msg = f"{args.get('message', '')} {args.get('response', '')}".lower()

        assert any(
            phrase in msg
            for phrase in [
                "what to play",
                "artist name",
                "service",
                "incomplete command",
                "keep speaking",
                "connector",
            ]
        ), (text, out)

def test_app_open_close_routes_are_preserved():
    _assert_arg("open spotify", "name", "spotify")
    _assert_action("open spotify", "OPEN_APP")

    _assert_arg("close spotify", "name", "spotify")
    _assert_action("close spotify", "CLOSE_APP")

    _assert_arg("close youtube", "name", "youtube")
    _assert_action("close youtube", "CLOSE_APP")

    _assert_arg("vera close youtube", "name", "youtube")
    _assert_action("vera close youtube", "CLOSE_APP")


def test_targeted_youtube_mpv_controls_are_preserved():
    _assert_action("pause youtube", "PAUSE_MEDIA")
    _assert_arg("pause youtube", "target", "youtube")

    _assert_action("youtube pause", "PAUSE_MEDIA")
    _assert_arg("youtube pause", "target", "youtube")

    _assert_action("pause mpv", "PAUSE_MEDIA")
    _assert_arg("pause mpv", "target", "mpv")

    _assert_action("pause and tv", "PAUSE_MEDIA")
    _assert_arg("pause and tv", "target", "mpv")


def test_youtube_and_spotify_play_queries_are_preserved():
    _assert_action("play youtube dr dre the watcher", "PLAY_MEDIA")
    _assert_arg("play youtube dr dre the watcher", "target", "youtube")
    _assert_arg("play youtube dr dre the watcher", "query", "dr dre the watcher")

    _assert_action("play the watcher by dr dre", "PLAY_MEDIA")
    _assert_arg("play the watcher by dr dre", "target", "spotify")
    _assert_arg("play the watcher by dr dre", "query", "the watcher by dr dre")

    _assert_action("play dmx on spotify", "PLAY_MEDIA")
    _assert_arg("play dmx on spotify", "target", "spotify")
    _assert_arg("play dmx on spotify", "query", "dmx")

    _assert_action("spotify play tupac all eyez", "PLAY_MEDIA")
    _assert_arg("spotify play tupac all eyez", "target", "spotify")
    _assert_arg("spotify play tupac all eyez", "query", "tupac all eyez")

    _assert_action("on spotify play tupac all eyez", "PLAY_MEDIA")
    _assert_arg("on spotify play tupac all eyez", "target", "spotify")
    _assert_arg("on spotify play tupac all eyez", "query", "tupac all eyez")

    _assert_action("play the fourth branch by immortal technique on spotify", "PLAY_MEDIA")
    _assert_arg("play the fourth branch by immortal technique on spotify", "target", "spotify")
    _assert_arg("play the fourth branch by immortal technique on spotify", "query", "the fourth branch by immortal technique")

    _assert_action("play the martyr by immortal technique on youtube", "PLAY_MEDIA")
    _assert_arg("play the martyr by immortal technique on youtube", "target", "youtube")
    _assert_arg("play the martyr by immortal technique on youtube", "query", "the martyr by immortal technique")


def test_implied_song_by_artist_defaults_to_spotify():
    _assert_action("all eyez on me by tupac", "PLAY_MEDIA")
    _assert_arg("all eyez on me by tupac", "target", "spotify")
    _assert_arg("all eyez on me by tupac", "query", "all eyez on me by tupac")
