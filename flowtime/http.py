"""Single outbound HTTP function so tests can replace every external call in one place."""

import requests


def send(method, url, **kwargs):
    return requests.request(method, url, **kwargs)
